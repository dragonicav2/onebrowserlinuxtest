"""
Builds a genuine Linux x86_64 Type-2 AppImage:
    dist/linux/ZeroDownloader-x86_64.AppImage

Combines the official AppImage Type-2 static ELF64 runtime (AI\\x02 header) with a
SquashFS 4.0 filesystem image of ZeroDownloader.AppDir (built via WSL mksquashfs when
available, or via an exact SquashFS 4.0 Little-Endian image builder fallback).
"""
import shutil
import struct
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPDIR_SRC = ROOT / "linux-appimage" / "ZeroDownloader.AppDir"
PORTABLE_PY = ROOT / "crossplatform" / "zerodownloader.py"
CACHE_DIR = ROOT / ".android-build-cache"
DIST_APPIMAGE = ROOT / "dist" / "linux" / "ZeroDownloader-x86_64.AppImage"

APPIMAGE_RUNTIME_URL = (
    "https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64"
)


def prepare_staging_appdir() -> Path:
    stage = ROOT / "obj_linux_appdir"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(APPDIR_SRC, stage)

    usr_bin = stage / "usr" / "bin"
    usr_bin.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PORTABLE_PY, usr_bin / "zerodownloader.py")
    shutil.copy2(stage / "zerodownloader.svg", stage / ".DirIcon")

    # Ensure strict Unix LF (\n) line endings on all scripts and metadata files
    for p in stage.rglob("*"):
        if p.is_file() and p.suffix in ("", ".py", ".desktop", ".svg") or p.name in ("AppRun", ".DirIcon"):
            raw = p.read_bytes().replace(b"\r\n", b"\n")
            p.write_bytes(raw)

    return stage


def fetch_type2_runtime() -> bytes:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    rt_path = CACHE_DIR / "appimage-runtime-x86_64"
    if not rt_path.exists() or rt_path.stat().st_size < 50_000:
        print(f"Downloading official AppImage Type-2 ELF64 runtime: {APPIMAGE_RUNTIME_URL}")
        req = urllib.request.Request(APPIMAGE_RUNTIME_URL, headers={"User-Agent": "ZeroDownloader-Builder/2.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if not data.startswith(b"\x7fELF"):
            raise RuntimeError("Downloaded AppImage runtime is not a valid ELF64 binary.")
        rt_path.write_bytes(data)
    return rt_path.read_bytes()


def try_wsl_mksquashfs(stage_dir: Path, out_sqfs: Path) -> bool:
    try:
        win_stage = str(stage_dir).replace("\\", "/")
        win_out = str(out_sqfs).replace("\\", "/")
        bash_cmd = (
            "set -e; "
            "command -v mksquashfs >/dev/null 2>&1; "
            f"STAGE=$(wslpath '{win_stage}'); "
            f"OUT=$(wslpath '{win_out}'); "
            "TMP=/tmp/zd_appdir_$$; rm -rf \"$TMP\"; cp -r \"$STAGE\" \"$TMP\"; "
            "chmod 0755 \"$TMP/AppRun\" \"$TMP/usr/bin/\"*.py; "
            "rm -f \"$OUT\"; "
            "mksquashfs \"$TMP\" \"$OUT\" -root-owned -noappend -comp gzip >/dev/null; "
            "rm -rf \"$TMP\""
        )
        res = subprocess.run(["wsl.exe", "-e", "sh", "-c", bash_cmd], timeout=20, capture_output=True)
        return res.returncode == 0 and out_sqfs.exists() and out_sqfs.stat().st_size > 1024
    except Exception:
        return False


def build_squashfs4_le(stage_dir: Path) -> bytes:
    """
    Pure-Python SquashFS 4.0 Little-Endian image builder (uncompressed data/metadata blocks,
    4096-byte aligned, preserving 0755 executable bits on AppRun and /usr/bin/*.py).
    Compatible with Linux kernel squashfs.ko, squashfuse (AppImage Type-2), and unsquashfs.
    """
    BLOCK_SIZE = 131072
    BLOCK_LOG = 17
    MTIME = int(time.time())
    # Flags: UNCOMPRESSED_INODES(1) | UNCOMPRESSED_DATA(2) | UNCOMPRESSED_DIRS(8)
    #      | NO_FRAGMENTS(0x10) | NO_XATTRS(0x200)
    SQFS_FLAGS = 0x0001 | 0x0002 | 0x0008 | 0x0010 | 0x0200

    class Node:
        def __init__(self, path: Path, name: str, is_dir: bool) -> None:
            self.path = path
            self.name = name
            self.is_dir = is_dir
            self.children: list[Node] = []
            self.inode_num = 0
            self.parent_inode = 1
            self.data_offset = 0
            self.block_sizes: list[int] = []
            self.inode_ref = 0  # (meta_block_offset << 16) | inner_offset
            self.dir_block_idx = 0
            self.dir_inner_off = 0
            self.dir_file_size = 3

    def scan(cur: Path, name: str) -> Node:
        node = Node(cur, name, cur.is_dir())
        if node.is_dir:
            for child in sorted(cur.iterdir(), key=lambda p: p.name.encode("utf-8")):
                node.children.append(scan(child, child.name))
        return node

    root = scan(stage_dir, "")

    # Assign 1-based inode numbers (post-order for children before parent dirs, root gets last or 1;
    # SquashFS requires directory entry inode deltas < 32767, sequential 1..N satisfies all).
    all_nodes: list[Node] = []

    def collect(n: Node, parent_ino: int) -> None:
        all_nodes.append(n)
        n.inode_num = len(all_nodes)
        n.parent_inode = parent_ino
        for ch in n.children:
            collect(ch, n.inode_num)

    collect(root, 1)

    # 1. Lay out file data starting right after 96-byte superblock
    data_buf = bytearray()
    cur_disk_pos = 96

    for n in all_nodes:
        if not n.is_dir:
            raw = n.path.read_bytes()
            n.data_offset = cur_disk_pos
            pos = 0
            while pos < len(raw):
                chunk = raw[pos : pos + BLOCK_SIZE]
                data_buf.extend(chunk)
                # Bit 24 (0x01000000) marks an uncompressed data block in SquashFS 4.0
                n.block_sizes.append(len(chunk) | 0x01000000)
                pos += len(chunk)
                cur_disk_pos += len(chunk)

    def pack_meta_table(raw_meta: bytes) -> tuple[bytes, list[int]]:
        """Splits metadata stream into <=8192-byte uncompressed SquashFS metadata blocks."""
        out = bytearray()
        block_starts: list[int] = []
        pos = 0
        if len(raw_meta) == 0:
            block_starts.append(0)
            out.extend(struct.pack("<H", 0x8000))
            return bytes(out), block_starts
        while pos < len(raw_meta):
            block_starts.append(len(out))
            chunk = raw_meta[pos : pos + 8192]
            out.extend(struct.pack("<H", len(chunk) | 0x8000))
            out.extend(chunk)
            pos += len(chunk)
        return bytes(out), block_starts

    # Two-pass build so directory entries have exact child inode_refs:
    # Pass A computes exact inode byte offsets inside the uncompressed inode stream.
    inode_inner_pos: dict[int, int] = {}
    dir_raw_streams: dict[int, bytes] = {}

    # Pre-size each node's inode record (Basic Dir = 32 bytes; Basic File = 32 + 4*len(blocks))
    running_ino_off = 0
    for n in all_nodes:
        inode_inner_pos[n.inode_num] = running_ino_off
        if n.is_dir:
            running_ino_off += 32
        else:
            running_ino_off += 32 + 4 * len(n.block_sizes)

    # Compute each node's (meta_block_start << 16) | inner_offset once inode_table_bytes is packed
    def meta_ref_for(stream_off: int) -> int:
        blk_idx = stream_off // 8192
        inner = stream_off % 8192
        # Each prior 8192-byte block occupies (2 + 8192) = 8194 bytes in packed table
        packed_blk_start = blk_idx * 8194
        return (packed_blk_start << 16) | inner

    for n in all_nodes:
        n.inode_ref = meta_ref_for(inode_inner_pos[n.inode_num])

    # Build uncompressed directory stream & record each directory's start_block/offset
    uncomp_dir_stream = bytearray()
    for n in all_nodes:
        if not n.is_dir:
            continue
        start_off = len(uncomp_dir_stream)
        blk_idx = start_off // 8192
        n.dir_block_idx = blk_idx * 8194
        n.dir_inner_off = start_off % 8192

        if not n.children:
            n.dir_file_size = 3
            continue

        # Single header group since all children share block/close inode numbers if same meta block;
        # group children by (child_inode_meta_block) as required by SquashFS 4.0!
        body = bytearray()
        idx = 0
        while idx < len(n.children):
            first = n.children[idx]
            grp_blk = first.inode_ref >> 16
            grp_base_ino = first.inode_num
            grp: list[Node] = []
            while idx < len(n.children):
                cand = n.children[idx]
                if (cand.inode_ref >> 16) != grp_blk or abs(cand.inode_num - grp_base_ino) > 30000 or len(grp) >= 256:
                    break
                grp.append(cand)
                idx += 1

            # squashfs_dir_header: count - 1 (uint32), start_block (uint32), inode_number (uint32)
            body.extend(struct.pack("<III", len(grp) - 1, grp_blk, grp_base_ino))
            for ch in grp:
                name_bytes = ch.name.encode("utf-8")
                ch_type = 1 if ch.is_dir else 2
                ino_delta = ch.inode_num - grp_base_ino
                body.extend(struct.pack("<HHhH", ch.inode_ref & 0xFFFF, ino_delta, ch_type, len(name_bytes) - 1))
                body.extend(name_bytes)

        n.dir_file_size = len(body) + 3
        dir_raw_streams[n.inode_num] = bytes(body)
        uncomp_dir_stream.extend(body)

    # Now serialize exact uncompressed inode stream
    uncomp_inode_stream = bytearray()
    for n in all_nodes:
        if n.is_dir:
            mode = 0o755
            nlink = 2 + sum(1 for c in n.children if c.is_dir)
            # squashfs_dir_inode_header: <HHHHIIIHHIH (32 bytes)
            uncomp_inode_stream.extend(
                struct.pack(
                    "<HHHHIIIHHIH",
                    1,  # SQUASHFS_DIR_TYPE
                    mode,
                    0,  # uid idx
                    0,  # gid idx
                    MTIME,
                    n.inode_num,
                    n.dir_block_idx,
                    nlink,
                    n.dir_file_size,
                    n.dir_inner_off,
                    n.parent_inode,
                )
            )
        else:
            is_exec = n.name == "AppRun" or n.name.endswith(".py") or n.name.endswith(".sh")
            mode = 0o755 if is_exec else 0o644
            fsize = n.path.stat().st_size
            # squashfs_reg_inode_header: <HHHHIIIIII (32 bytes) + uint32 block_list[]
            uncomp_inode_stream.extend(
                struct.pack(
                    "<HHHHIIIIII",
                    2,  # SQUASHFS_REG_TYPE
                    mode,
                    0,
                    0,
                    MTIME,
                    n.inode_num,
                    n.data_offset,
                    0xFFFFFFFF,  # no fragment
                    0,
                    fsize,
                )
            )
            for bsz in n.block_sizes:
                uncomp_inode_stream.extend(struct.pack("<I", bsz))

    inode_table_bytes, _ = pack_meta_table(bytes(uncomp_inode_stream))
    dir_table_bytes, _ = pack_meta_table(bytes(uncomp_dir_stream))
    id_meta_bytes, _ = pack_meta_table(struct.pack("<I", 0))

    inode_table_start = 96 + len(data_buf)
    dir_table_start = inode_table_start + len(inode_table_bytes)
    id_meta_pos = dir_table_start + len(dir_table_bytes)
    id_table_start = id_meta_pos + len(id_meta_bytes)
    id_lookup_bytes = struct.pack("<Q", id_meta_pos)

    bytes_used = id_table_start + len(id_lookup_bytes)

    superblock = struct.pack(
        "<IIIIIHHHHHHQQQQQQQQ",
        0x73717368,          # s_magic ("hsqs")
        len(all_nodes),      # inodes
        MTIME,               # mkfs_time
        BLOCK_SIZE,          # block_size
        0,                   # fragments
        1,                   # compression (ZLIB id=1)
        BLOCK_LOG,           # block_log
        SQFS_FLAGS,          # flags
        1,                   # no_ids
        4,                   # s_major
        0,                   # s_minor
        root.inode_ref,      # root_inode
        bytes_used,          # bytes_used
        id_table_start,      # id_table_start
        0xFFFFFFFFFFFFFFFF,  # xattr_id_table_start
        inode_table_start,   # inode_table_start
        dir_table_start,     # directory_table_start
        0xFFFFFFFFFFFFFFFF,  # fragment_table_start
        0xFFFFFFFFFFFFFFFF,  # export_table_start
    )
    assert len(superblock) == 96

    image = bytearray()
    image.extend(superblock)
    image.extend(data_buf)
    image.extend(inode_table_bytes)
    image.extend(dir_table_bytes)
    image.extend(id_meta_bytes)
    image.extend(id_lookup_bytes)

    # Pad SquashFS image to 4096-byte boundary per SquashFS/AppImage standard
    rem = len(image) % 4096
    if rem != 0:
        image.extend(b"\x00" * (4096 - rem))
    return bytes(image)


def main() -> None:
    stage = prepare_staging_appdir()
    runtime_bytes = fetch_type2_runtime()

    DIST_APPIMAGE.parent.mkdir(parents=True, exist_ok=True)
    sqfs_temp = ROOT / "obj_linux_appdir.squashfs"
    if sqfs_temp.exists():
        sqfs_temp.unlink()

    if try_wsl_mksquashfs(stage, sqfs_temp):
        print("Built SquashFS payload via WSL mksquashfs.")
        sqfs_bytes = sqfs_temp.read_bytes()
        sqfs_temp.unlink(missing_ok=True)
    else:
        print("Built SquashFS 4.0 Little-Endian payload via native Python builder.")
        sqfs_bytes = build_squashfs4_le(stage)

    assert sqfs_bytes[:4] == b"hsqs", "Invalid SquashFS magic header!"
    assert runtime_bytes[:4] == b"\x7fELF" and runtime_bytes[8:11] == b"AI\x02", "Invalid Type-2 AppImage ELF runtime!"

    DIST_APPIMAGE.write_bytes(runtime_bytes + sqfs_bytes)
    shutil.rmtree(stage, ignore_errors=True)
    print(f"SUCCESS: Built Linux x86_64 AppImage -> {DIST_APPIMAGE} ({DIST_APPIMAGE.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
