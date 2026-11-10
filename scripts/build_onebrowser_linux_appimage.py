"""
Builds a genuine Linux x86_64 Type-2 AppImage for OneBrowser Zen Edition
(packaged with Zen Vertical Sidebar, Workspaces, Streaming Controls, and 16x ZeroDownloader):
    dist/linux/OneBrowser-x86_64.AppImage
"""
import os
import shutil
import subprocess
from pathlib import Path

from build_linux_appimage import build_squashfs4_le, fetch_type2_runtime, try_wsl_mksquashfs

ROOT = Path(__file__).resolve().parent.parent
APPDIR_SRC = ROOT / "linux-appimage" / "OneBrowser.AppDir"
PORTABLE_PY = ROOT / "crossplatform" / "zerodownloader.py"
DIST_APPIMAGE = ROOT / "dist" / "linux" / "OneBrowser-x86_64.AppImage"


def prepare_staging_appdir() -> Path:
    stage = ROOT / "obj_linux_ob_appdir"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(APPDIR_SRC, stage)

    usr_bin = stage / "usr" / "bin"
    usr_bin.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PORTABLE_PY, usr_bin / "zerodownloader.py")
    shutil.copy2(ROOT / "crossplatform" / "youtube_adblock_rules.json", usr_bin / "youtube_adblock_rules.json")
    shutil.copy2(ROOT / "crossplatform" / "youtube_adblock_engine.js", usr_bin / "youtube_adblock_engine.js")
    shutil.copy2(stage / "onebrowser.svg", stage / ".DirIcon")

    for p in stage.rglob("*"):
        if p.is_file() and (p.suffix in ("", ".py", ".js", ".json", ".desktop", ".svg") or p.name in ("AppRun", ".DirIcon")):
            p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n"))
        if p.is_file() and (p.name == "AppRun" or p.suffix == ".py"):
            try:
                os.chmod(p, 0o755)
            except Exception:
                pass

    return stage


def try_native_linux_mksquashfs(stage: Path, out_sqfs: Path) -> bool:
    if os.name == "nt" or not shutil.which("mksquashfs"):
        return False
    try:
        os.chmod(stage / "AppRun", 0o755)
        for py in (stage / "usr" / "bin").glob("*.py"):
            os.chmod(py, 0o755)
        res = subprocess.run(
            ["mksquashfs", str(stage), str(out_sqfs), "-root-owned", "-noappend", "-comp", "gzip"],
            capture_output=True,
            timeout=30,
        )
        return res.returncode == 0 and out_sqfs.is_file() and out_sqfs.stat().st_size > 512
    except Exception:
        return False


def main() -> None:
    stage = prepare_staging_appdir()
    runtime_bytes = fetch_type2_runtime()

    DIST_APPIMAGE.parent.mkdir(parents=True, exist_ok=True)
    sqfs_temp = ROOT / "obj_linux_ob_appdir.squashfs"
    if sqfs_temp.exists():
        sqfs_temp.unlink()

    if try_native_linux_mksquashfs(stage, sqfs_temp):
        print("Built OneBrowser SquashFS payload via native Linux mksquashfs.")
        sqfs_bytes = sqfs_temp.read_bytes()
        sqfs_temp.unlink(missing_ok=True)
    elif try_wsl_mksquashfs(stage, sqfs_temp):
        print("Built OneBrowser SquashFS payload via WSL mksquashfs.")
        sqfs_bytes = sqfs_temp.read_bytes()
        sqfs_temp.unlink(missing_ok=True)
    else:
        print("Built OneBrowser SquashFS 4.0 Little-Endian payload via native Python builder.")
        sqfs_bytes = build_squashfs4_le(stage)

    assert sqfs_bytes[:4] == b"hsqs", "Invalid SquashFS magic header!"
    assert runtime_bytes[:4] == b"\x7fELF" and runtime_bytes[8:11] == b"AI\x02", "Invalid Type-2 AppImage ELF runtime!"

    DIST_APPIMAGE.write_bytes(runtime_bytes + sqfs_bytes)
    try:
        os.chmod(DIST_APPIMAGE, 0o755)
    except Exception:
        pass
    shutil.rmtree(stage, ignore_errors=True)
    print(f"SUCCESS: Built Linux OneBrowser Zen AppImage -> {DIST_APPIMAGE} ({DIST_APPIMAGE.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
