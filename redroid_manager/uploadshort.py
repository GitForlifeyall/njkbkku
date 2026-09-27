"""
Redroid Multi-Instance Upload Worker Stub
=========================================
Executes YouTube Shorts / Video upload workflows on isolated Redroid container instances.
Accepts target ADB device address, brand identifier, and media metadata.

Usage:
    python uploadshort.py --device 127.0.0.1:5555 --brand brand_01 --title "My Sample Short"
"""

import argparse
import os
import sys
import time
import subprocess
import shutil
from pathlib import Path
from typing import Optional

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass


def log(msg: str):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def find_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    common_paths = [
        Path(r"C:\Users\Shahid\tools\scrcpy") / f"{name}.exe",
        Path(r"C:\tools\scrcpy") / f"{name}.exe",
        Path(r"C:\platform-tools") / f"{name}.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / f"{name}.exe",
    ]
    for p in common_paths:
        if p.exists():
            return str(p)
    return name


def run_adb(adb_exe: str, target: str, *args: str) -> subprocess.CompletedProcess:
    cmd = [adb_exe, "-s", target] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


YT_UPLOADER_DIR = Path(__file__).resolve().parent.parent / "ytuploader"
if str(YT_UPLOADER_DIR) not in sys.path:
    sys.path.insert(0, str(YT_UPLOADER_DIR))

try:
    from upload_short import upload_short_to_youtube
except ImportError as err:
    upload_short_to_youtube = None


def upload_short(
    adb_exe: str,
    target: str,
    brand_id: str,
    video_path: Optional[str] = None,
    title: Optional[str] = None,
    sound: Optional[str] = None,
    timestamp: Optional[str] = None
) -> bool:
    log("========================================================")
    log(f"  REDROID UPLOAD WORKER - BRAND: {brand_id}")
    log(f"  Target Device: {target}")
    log(f"  Video Source:  {video_path or 'None'}")
    log(f"  Title:         {title or 'Automated Short #' + brand_id}")
    log(f"  Sound Track:   {sound or 'None'}")
    log(f"  Timestamp:     {timestamp or 'Default'}")
    log("========================================================")

    if not video_path or not os.path.exists(video_path):
        log(f"[ERROR] Video file not found: {video_path}")
        return False

    if upload_short_to_youtube is None:
        log("[ERROR] Could not import upload_short_to_youtube from ytuploader/upload_short.py")
        return False

    import tempfile
    import threading

    pause_flag = Path(tempfile.gettempdir()) / f"redroid_pause_{brand_id}.flag"
    if pause_flag.exists():
        try:
            pause_flag.unlink()
        except Exception:
            pass

    pause_event = threading.Event()
    pause_event.set()
    stop_watcher = threading.Event()

    def _pause_watcher():
        while not stop_watcher.is_set():
            try:
                if pause_flag.exists():
                    if pause_event.is_set():
                        pause_event.clear()
                        log("[!] ⏸ Upload automation PAUSED. Waiting for resume...")
                else:
                    if not pause_event.is_set():
                        pause_event.set()
                        log("[!] ▶ Upload automation RESUMED.")
            except Exception:
                pass
            time.sleep(0.3)

    watcher_thread = threading.Thread(target=_pause_watcher, daemon=True)
    watcher_thread.start()

    try:
        short_title = title or Path(video_path).stem
        upload_short_to_youtube(
            adb_exe=adb_exe,
            target=target,
            video_path=video_path,
            title=short_title,
            sound=sound,
            timestamp=timestamp,
            log_fn=log,
            pause_event=pause_event
        )
        stop_watcher.set()
        if pause_flag.exists():
            try:
                pause_flag.unlink()
            except Exception:
                pass
        log("========================================================")
        log(f"[SUCCESS] Real upload job for {brand_id} finished successfully!")
        log("========================================================")
        return True
    except Exception as e:
        stop_watcher.set()
        if pause_flag.exists():
            try:
                pause_flag.unlink()
            except Exception:
                pass
        log(f"[ERROR] Exception during real UI upload automation: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Redroid Multi-Instance Upload Worker")
    parser.add_argument("--device", required=True, help="ADB target address (e.g. 127.0.0.1:5555)")
    parser.add_argument("--brand", required=True, help="Brand identifier (e.g. brand_01)")
    parser.add_argument("--video", default=None, help="Path to video file (.mp4)")
    parser.add_argument("--title", default=None, help="Short / Reel title")
    parser.add_argument("--sound", default=None, help="Audio track query")
    parser.add_argument("--timestamp", default=None, help="Audio start timestamp")
    parser.add_argument("--adb", default=None, help="Path to adb executable")

    args = parser.parse_args()
    adb_exe = args.adb or find_tool("adb")

    success = upload_short(
        adb_exe=adb_exe,
        target=args.device,
        brand_id=args.brand,
        video_path=args.video,
        title=args.title,
        sound=args.sound,
        timestamp=args.timestamp
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
