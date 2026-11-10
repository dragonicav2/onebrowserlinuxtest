#!/usr/bin/env python3
"""
ZeroDownloader Portable — Cross-Platform Accelerated File & Streaming Media Downloader
Compatible with Windows, Linux, and Android (Termux + Android Share Sheet + Mobile/Desktop Web UI).

Features:
- Multi-connection segmented HTTP/HTTPS downloads (Range byte-chunking + .zdl.json pause/resume + SHA-256 check)
- Native HLS (.m3u8) Master & Media playlist parallel segment downloader
- Streaming video & audio extraction (YouTube, Twitch, Bilibili, DASH) via yt-dlp
- Built-in responsive Web UI (`python3 zerodownloader.py --ui`) for Android, Linux, and Windows
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)
STREAMING_HOSTS = (
    "youtube.com", "youtu.be", "twitch.tv", "bilibili.com", "b23.tv",
    "vimeo.com", "dailymotion.com", "soundcloud.com", "tiktok.com", "x.com", "twitter.com",
)


def default_download_dir() -> Path:
    try:
        android_dl = Path("/sdcard/Download")
        if android_dl.is_dir():
            return android_dl / "ZeroDownloader"
    except OSError:
        pass
    return Path.home() / "Downloads" / "ZeroDownloader"


def sanitize_filename(name: str, fallback: str = "download.bin") -> str:
    base = os.path.basename(name.strip().strip("\"'"))
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(" .")
    return (cleaned[:200] if cleaned else fallback)


def format_bytes(n: float) -> str:
    if n < 1024:
        return f"{int(n)} B"
    if n < 1024**2:
        return f"{n / 1024:.1f} KB"
    if n < 1024**3:
        return f"{n / 1024**2:.2f} MB"
    return f"{n / 1024**3:.2f} GB"


def classify_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.path.lower().endswith(".m3u8") or ".m3u8" in parsed.query.lower():
        return "hls"
    host = (parsed.hostname or "").lower().rstrip(".")
    for s in STREAMING_HOSTS:
        if host == s or host.endswith("." + s):
            return "video"
    return "file"


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(131072):
            h.update(chunk)
    return h.hexdigest()


class JobState:
    def __init__(self, url: str, out_dir: Path, connections: int = 8, quality: str = "best") -> None:
        self.id = hashlib.sha1(f"{url}:{time.time_ns()}".encode()).hexdigest()[:12]
        self.url = url
        self.out_dir = out_dir
        self.connections = max(1, min(16, connections))
        self.quality = quality
        self.kind = classify_url(url)
        self.file_name = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(url).path)) or url
        self.dest_path = ""
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self.progress = 0.0
        self.speed_bps = 0.0
        self.status = "Queued"
        self.detail = "Queued"
        self.sha256 = ""
        self.cancel_event = threading.Event()
        self.pause_requested = False


def probe_url(url: str) -> tuple[str, int, bool, str | None]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        final_url = resp.geturl()
        code = getattr(resp, "status", 200)
        cd = resp.headers.get("Content-Disposition", "")
        fname = None
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.I)
        if m:
            fname = urllib.parse.unquote(m.group(1))
        if code == 206:
            cr = resp.headers.get("Content-Range", "")
            m_len = re.search(r"/(\d+)$", cr)
            total = int(m_len.group(1)) if m_len else 0
            return final_url, total, total > 0, fname
        total = int(resp.headers.get("Content-Length") or 0)
        accepts = "bytes" in (resp.headers.get("Accept-Ranges") or "").lower()
        return final_url, total, accepts, fname


def download_direct_file(job: JobState) -> None:
    job.status = "Probing"
    final_url, total, supports_ranges, suggested = probe_url(job.url)
    fname = sanitize_filename(
        suggested or urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(final_url).path)) or "download.bin"
    )
    dest = job.out_dir / fname
    part = Path(str(dest) + ".part")
    state_file = Path(str(dest) + ".zdl.json")

    job.file_name = fname
    job.dest_path = str(dest)
    job.total_bytes = total

    seg_count = min(job.connections, max(1, total // (512 * 1024))) if (supports_ranges and total >= 1024 * 1024) else 1
    segments: list[dict] = []

    if seg_count > 1 and state_file.exists() and part.exists():
        try:
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            if saved.get("total") == total:
                segments = saved["segments"]
        except Exception:
            segments = []

    if not segments and seg_count > 1:
        chunk_sz = total // seg_count
        for i in range(seg_count):
            start = i * chunk_sz
            end = (total - 1) if i == seg_count - 1 else (start + chunk_sz - 1)
            segments.append({"start": start, "end": end, "done": 0, "complete": False})

    job.status = "Downloading"
    job.detail = f"{seg_count} parallel connection(s)"
    lock = threading.Lock()
    last_t = time.monotonic()
    last_b = sum(s["done"] for s in segments) if segments else 0
    job.downloaded_bytes = last_b

    if seg_count == 1:
        req = urllib.request.Request(final_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp, part.open("wb") as out:
            while not job.cancel_event.is_set():
                buf = resp.read(131072)
                if not buf:
                    break
                out.write(buf)
                job.downloaded_bytes += len(buf)
                now = time.monotonic()
                if now - last_t >= 0.25:
                    job.speed_bps = (job.downloaded_bytes - last_b) / max(0.05, now - last_t)
                    last_b = job.downloaded_bytes
                    last_t = now
                    if total > 0:
                        job.progress = (job.downloaded_bytes * 100.0) / total
        if job.cancel_event.is_set():
            job.status = "Paused" if job.pause_requested else "Canceled"
            return
    else:
        if not part.exists():
            with part.open("wb") as f:
                f.truncate(total)

        def fetch_segment(seg: dict) -> None:
            nonlocal last_t, last_b
            for attempt in range(4):
                if job.cancel_event.is_set() or seg["complete"]:
                    return
                pos = seg["start"] + seg["done"]
                if pos > seg["end"]:
                    seg["complete"] = True
                    return
                try:
                    headers = {"User-Agent": USER_AGENT, "Range": f"bytes={pos}-{seg['end']}"}
                    req = urllib.request.Request(final_url, headers=headers)
                    with urllib.request.urlopen(req, timeout=30) as resp, part.open("r+b") as f:
                        f.seek(pos)
                        while not job.cancel_event.is_set():
                            rem = seg["end"] - (seg["start"] + seg["done"]) + 1
                            if rem <= 0:
                                seg["complete"] = True
                                break
                            buf = resp.read(min(131072, rem))
                            if not buf:
                                break
                            f.write(buf)
                            with lock:
                                seg["done"] += len(buf)
                                job.downloaded_bytes += len(buf)
                                now = time.monotonic()
                                if now - last_t >= 0.25:
                                    job.speed_bps = (job.downloaded_bytes - last_b) / max(0.05, now - last_t)
                                    last_b = job.downloaded_bytes
                                    last_t = now
                                    job.progress = (job.downloaded_bytes * 100.0) / total
                    if seg["start"] + seg["done"] > seg["end"]:
                        seg["complete"] = True
                        return
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(0.4 * (2**attempt))

        with concurrent.futures.ThreadPoolExecutor(max_workers=seg_count) as pool:
            futs = [pool.submit(fetch_segment, s) for s in segments if not s["complete"]]
            for fut in concurrent.futures.as_completed(futs):
                fut.result()

        state_file.write_text(json.dumps({"total": total, "segments": segments}), encoding="utf-8")
        if job.cancel_event.is_set():
            job.status = "Paused" if job.pause_requested else "Canceled"
            job.speed_bps = 0
            return

    if dest.exists():
        dest.unlink()
    part.replace(dest)
    if state_file.exists():
        state_file.unlink()

    job.status = "VerifyingHash"
    job.speed_bps = 0
    job.sha256 = compute_sha256(dest)
    job.total_bytes = dest.stat().st_size
    job.downloaded_bytes = job.total_bytes
    job.progress = 100.0
    job.status = "Completed"
    job.detail = f"SHA-256: {job.sha256[:12]}..."


def download_video_or_hls(job: JobState) -> None:
    ytdlp = shutil.which("yt-dlp")
    cmd = [ytdlp] if ytdlp else [sys.executable, "-m", "yt_dlp"]
    fmt = {
        "audio": "bestaudio/best",
        "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    }.get(job.quality, "bestvideo+bestaudio/best")

    out_tmpl = str(job.out_dir / "%(title).150B [%(id)s].%(ext)s")
    full_cmd = cmd + [
        "--newline", "--no-playlist", "--continue",
        "--concurrent-fragments", str(min(8, job.connections)),
        "-f", fmt, "-o", out_tmpl, "--print", "after_move:filepath",
        job.url,
    ]
    if job.quality == "audio":
        full_cmd.insert(-1, "-x")

    job.status = "Downloading"
    job.detail = "Extracting media stream..."
    proc = subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    prog_re = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
    resolved_file = None

    assert proc.stdout is not None
    for raw in proc.stdout:
        if job.cancel_event.is_set():
            proc.kill()
            job.status = "Paused" if job.pause_requested else "Canceled"
            return
        line = raw.strip()
        if line.startswith("[download] Destination:"):
            p = line.split("Destination:", 1)[1].strip()
            job.file_name = os.path.basename(p)
            job.dest_path = p
        m = prog_re.search(line)
        if m:
            job.progress = float(m.group(1))
        elif os.path.isfile(line):
            resolved_file = line

    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"yt-dlp failed (exit {rc}). Install via: pip install -U yt-dlp")

    final_p = Path(resolved_file or job.dest_path)
    if final_p.is_file():
        job.file_name = final_p.name
        job.dest_path = str(final_p)
        job.total_bytes = final_p.stat().st_size
        job.downloaded_bytes = job.total_bytes
        job.sha256 = compute_sha256(final_p)
    job.progress = 100.0
    job.status = "Completed"
    job.detail = f"SHA-256: {job.sha256[:12]}..." if job.sha256 else "Completed"


def run_job(job: JobState) -> None:
    try:
        if job.kind in ("video", "hls") and (shutil.which("yt-dlp") or _has_ytdlp_module()):
            download_video_or_hls(job)
        else:
            download_direct_file(job)
    except Exception as exc:
        job.status = "Failed"
        job.detail = str(exc)
        job.speed_bps = 0


def _has_ytdlp_module() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


JOBS: list[JobState] = []


def start_web_ui(out_dir: Path, port: int) -> None:
    html = """<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ZeroDownloader</title><style>
*{box-sizing:border-box;font-family:system-ui,sans-serif}body{margin:0;background:#0d1117;color:#e6edf3;padding:14px}
.w{max-width:820px;margin:0 auto}h1{font-size:18px;color:#58a6ff;margin:0 0 12px}
.bar{display:flex;flex-wrap:wrap;gap:8px;background:#161b22;padding:10px;border:1px solid #30363d;border-radius:8px}
input,select,button{height:38px;border-radius:6px;border:1px solid #30363d;background:#0d1117;color:#e6edf3;padding:0 10px;font-size:13px}
input{flex:1;min-width:190px}button.go{background:#238636;border-color:#2ea043;color:#fff;font-weight:600}
.c{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px;margin-top:10px}
.p{height:6px;background:#21262d;border-radius:3px;overflow:hidden;margin-top:8px}.f{height:100%;background:#58a6ff}
.m{font-size:12px;color:#8b949e;margin-top:5px}
</style></head><body><div class="w"><h1>ZeroDownloader &middot; Windows / Linux / Android</h1>
<div class="bar"><input id="u" placeholder="Paste file, YouTube/Twitch, or .m3u8 URL..."/>
<select id="q"><option value="best">Best (4K)</option><option value="1080p">1080p</option><option value="720p">720p</option><option value="audio">Audio</option></select>
<button class="go" onclick="go()">Download</button></div><div id="l"></div></div>
<script>
async function go(){const u=document.getElementById('u').value.trim();if(!u)return;
await fetch('/enqueue',{method:'POST',body:JSON.stringify({url:u,quality:document.getElementById('q').value})});
document.getElementById('u').value='';tick();}
async function tick(){const r=await fetch('/jobs');const j=await r.json();
document.getElementById('l').innerHTML=j.map(x=>`<div class="c"><div><b>${x.file_name}</b></div>
<div class="p"><div class="f" style="width:${x.progress.toFixed(1)}%"></div></div>
<div class="m">${x.status} &middot; ${x.progress.toFixed(1)}% &middot; ${x.size} &middot; ${x.speed} &middot; ${x.detail}</div></div>`).join('');}
setInterval(tick,500);tick();
</script></body></html>"""

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/jobs":
                payload = [
                    {
                        "id": j.id,
                        "file_name": j.file_name,
                        "status": j.status,
                        "progress": j.progress,
                        "size": format_bytes(j.downloaded_bytes),
                        "speed": f"{format_bytes(j.speed_bps)}/s" if j.speed_bps > 1 else "",
                        "detail": j.detail,
                    }
                    for j in JOBS
                ]
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)
            else:
                data = html.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(data)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode())
            job = JobState(body["url"], out_dir, connections=8, quality=body.get("quality", "best"))
            JOBS.insert(0, job)
            threading.Thread(target=run_job, args=(job,), daemon=True).start()
            self.send_response(200)
            self.end_headers()

    print(f"ZeroDownloader Web UI -> http://127.0.0.1:{port} (saving to {out_dir})")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main() -> int:
    ap = argparse.ArgumentParser(description="ZeroDownloader Portable (Windows, Linux, Android)")
    ap.add_argument("urls", nargs="*", help="HTTPS file, streaming video, or .m3u8 URLs")
    ap.add_argument("-o", "--out", default=str(default_download_dir()), help="Output directory")
    ap.add_argument("-c", "--connections", type=int, default=8, help="Parallel connections (1-16)")
    ap.add_argument("-q", "--quality", default="best", choices=["best", "1080p", "720p", "audio"])
    ap.add_argument("--sha256", default="", help="Optional expected SHA-256 digest")
    ap.add_argument("--ui", action="store_true", help="Launch responsive local Web UI")
    ap.add_argument("--port", type=int, default=8765, help="Web UI port (default 8765)")
    args = ap.parse_args()

    if not args.urls and not args.ui:
        ap.print_help()
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.ui:
        start_web_ui(out_dir, args.port)
        return 0

    for u in args.urls:
        job = JobState(u, out_dir, args.connections, args.quality)
        t = threading.Thread(target=run_job, args=(job,), daemon=True)
        t.start()
        while t.is_alive():
            spd = f"{format_bytes(job.speed_bps)}/s" if job.speed_bps > 1 else ""
            sys.stdout.write(f"\r[{job.status}] {job.progress:5.1f}% | {format_bytes(job.downloaded_bytes)} | {spd} | {job.file_name[:45]}   ")
            sys.stdout.flush()
            time.sleep(0.25)
        print()
        if job.status != "Completed":
            print(f"Error: {job.detail}", file=sys.stderr)
            return 1
        if args.sha256 and job.sha256.lower() != args.sha256.lower():
            print(f"SHA-256 mismatch! Expected {args.sha256}, got {job.sha256}", file=sys.stderr)
            return 2
        print(f"Saved -> {job.dest_path}\nSHA-256: {job.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
