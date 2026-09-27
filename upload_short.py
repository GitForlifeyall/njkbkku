"""
YouTube Short Uploader for Redroid Android Instances (Direct Fast Mode)
=======================================================================
Automates pushing and uploading YouTube Shorts directly from local video files
to the logged-in YouTube channel on a Redroid Android instance.

Usage:
    python upload_short.py -u <video_path> [-v] [--account 01] [--title "Short Title"]
    python upload_short.py <video_path> -u -v -s "Song Name"
"""

import argparse
import os
import sys
import time
import subprocess
import re
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Callable

DEFAULT_TOOLS_DIR = Path(r"C:\Users\Shahid\tools\scrcpy")
DEFAULT_ADB = DEFAULT_TOOLS_DIR / "adb.exe"
DEFAULT_SCRCPY = DEFAULT_TOOLS_DIR / "scrcpy.exe"

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass


class UploadCancelledException(Exception):
    """Raised when an upload is stopped/cancelled by the user."""
    pass


def find_tool(name: str, fallback_path: Path) -> str:
    if fallback_path.exists():
        return str(fallback_path)
    import shutil
    found = shutil.which(name)
    if found:
        return found
    return name


def run_adb(adb_exe: str, target: str, *args, check=False, timeout: Optional[float] = 15.0) -> subprocess.CompletedProcess:
    cmd = [adb_exe, "-s", target] + list(args)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=check, encoding="utf-8", errors="ignore", timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="Command timed out")


def get_wsl_ip() -> Optional[str]:
    try:
        res = subprocess.run(["wsl", "-d", "Ubuntu", "-e", "ip", "-4", "addr", "show", "eth0"], capture_output=True, text=True, errors="ignore")
        m = re.search(r"inet\s+([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", res.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    try:
        res = subprocess.run(["wsl", "hostname", "-i"], capture_output=True, text=True, errors="ignore")
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip().split()[0]
    except Exception:
        pass
    return None


def sleep_with_control(seconds: float, pause_event: Optional[threading.Event] = None, stop_event: Optional[threading.Event] = None):
    """Sleeps in tiny 50ms increments to allow immediate pausing or stopping."""
    end_time = time.time() + seconds
    while time.time() < end_time:
        if stop_event and stop_event.is_set():
            raise UploadCancelledException("Upload cancelled by user.")
        if pause_event and not pause_event.is_set():
            while not pause_event.is_set():
                if stop_event and stop_event.is_set():
                    raise UploadCancelledException("Upload cancelled by user.")
                time.sleep(0.05)
        time.sleep(min(0.05, max(0.0, end_time - time.time())))


def should_ignore_log(msg: str) -> bool:
    m = str(msg).lower()
    return any(k in m for k in ["default ssl", "defaultssl", "sslcontext", "trustmanager", "sslhandshake", "sslexception"])


def connect_adb(adb_exe: str, target: str, max_retries: int = 8, log_fn: Optional[Callable[[str], None]] = None) -> str:
    def _l(msg):
        if should_ignore_log(msg):
            return
        if log_fn:
            log_fn(msg)
        else:
            print(msg, flush=True)

    _l(f"[*] Connecting to Android instance at {target}...")

    # First check existing online devices on this port
    port = target.split(":")[-1]
    res = subprocess.run([adb_exe, "devices"], capture_output=True, text=True, encoding="utf-8", errors="ignore")
    for line in res.stdout.splitlines():
        if f":{port}" in line and "device" in line and "offline" not in line:
            active_target = line.split()[0]
            _l(f"[+] Reusing active online target: {active_target}")
            return active_target

    # Try connecting directly
    for _ in range(max_retries // 2):
        subprocess.run([adb_exe, "connect", target], capture_output=True)
        res = subprocess.run([adb_exe, "devices"], capture_output=True, text=True, encoding="utf-8", errors="ignore")
        for line in res.stdout.splitlines():
            if target in line and "device" in line and "offline" not in line:
                _l(f"[+] Connected to {target}")
                return target
        time.sleep(0.8)

    # If local target failed or offline, find WSL IP
    wsl_ip = get_wsl_ip()
    if wsl_ip:
        fallback_target = f"{wsl_ip}:{port}"
        _l(f"[*] Connecting to WSL2 target at {fallback_target}...")
        for _ in range(max_retries // 2):
            subprocess.run([adb_exe, "connect", fallback_target], capture_output=True)
            res = subprocess.run([adb_exe, "devices"], capture_output=True, text=True, encoding="utf-8", errors="ignore")
            for line in res.stdout.splitlines():
                if fallback_target in line and "device" in line and "offline" not in line:
                    _l(f"[+] Connected to {fallback_target}")
                    return fallback_target
            time.sleep(0.8)

    return target


def is_scrcpy_running() -> bool:
    try:
        res = subprocess.run(["tasklist"], capture_output=True, text=True, errors="ignore")
        return "scrcpy.exe" in res.stdout.lower()
    except Exception:
        return False


def launch_scrcpy(scrcpy_exe: str, target: str, log_fn: Optional[Callable[[str], None]] = None):
    def _l(msg):
        if log_fn:
            log_fn(msg)
        else:
            print(msg, flush=True)

    if is_scrcpy_running():
        _l("[+] Screen viewer (scrcpy) is already active.")
        return

    _l(f"[*] Launching scrcpy viewer for {target}...")
    try:
        subprocess.Popen(
            [scrcpy_exe, "-s", target, "--video-codec=h264", "--video-encoder=OMX.google.h264.encoder", "--no-audio", "--video-bit-rate=4M", "--max-fps=30", "--stay-awake", "--window-title", f"Redroid - {target}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        )
        _l("[+] Screen viewer opened successfully!")
    except Exception as e:
        _l(f"[!] Could not launch scrcpy: {e}")


def clean_emulator_media(adb_exe: str, target: str, log_fn: Optional[Callable[[str], None]] = None):
    """Completely removes all existing media files and resets the Android MediaStore database."""
    def _l(msg):
        if log_fn:
            log_fn(msg)
        else:
            print(msg, flush=True)

    _l("[*] Fully cleaning emulator media directories and MediaStore records...")
    clean_cmd = (
        "rm -rf /storage/emulated/0/Movies/* /storage/emulated/0/Download/* /storage/emulated/0/DCIM/* 2>/dev/null; "
        "mkdir -p /storage/emulated/0/Movies /storage/emulated/0/Download /storage/emulated/0/DCIM; "
        "chmod -R 777 /storage/emulated/0/Movies /storage/emulated/0/Download /storage/emulated/0/DCIM; "
        "content delete --uri content://media/external/video/media; "
        "content delete --uri content://media/external/images/media"
    )
    run_adb(adb_exe, target, "shell", clean_cmd)
    _l("[+] Emulator media storage and MediaStore cleaned.")


def clean_youtube_upload_session(adb_exe: str, target: str, yt_pkg: str, log_fn: Optional[Callable[[str], None]] = None):
    """Terminates YouTube and clears pending upload database jobs and working caches."""
    def _l(msg):
        if log_fn:
            log_fn(msg)
        else:
            print(msg, flush=True)

    _l(f"[*] Terminating {yt_pkg} and clearing stale upload drafts/sessions...")
    run_adb(adb_exe, target, "shell", "am", "force-stop", yt_pkg)
    # Clear upload job SQLite database
    run_adb(adb_exe, target, "shell", f"su 0 sqlite3 /data/data/{yt_pkg}/databases/youtube_upload_service 'DELETE FROM job_storage_jobs;' 2>/dev/null || true")
    # Clear upload working directories, project drafts, and caches
    draft_paths = (
        f"/data/user/0/{yt_pkg}/files/shorts_project "
        f"/data/user/0/{yt_pkg}/files/userwasinshorts "
        f"/data/user/0/{yt_pkg}/files/upload "
        f"/data/user/0/{yt_pkg}/app_youtube_upload/* "
        f"/data/user/0/{yt_pkg}/cache/*"
    )
    run_adb(adb_exe, target, "shell", f"su 0 rm -rf {draft_paths} 2>/dev/null || true")
    _l("[+] YouTube upload session and cache cleared.")


def push_and_index_video(adb_exe: str, target: str, local_path: str, media_name: Optional[str] = None,
                         log_fn: Optional[Callable[[str], None]] = None,
                         pause_event: Optional[threading.Event] = None, stop_event: Optional[threading.Event] = None) -> str:
    def _l(msg):
        if log_fn:
            log_fn(msg)
        else:
            print(msg, flush=True)

    path_obj = Path(local_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Video file not found at: {local_path}")

    file_size_mb = path_obj.stat().st_size / (1024 * 1024)
    ts = int(time.time())
    if media_name:
        clean_name = str(media_name).strip()
        base_stem = Path(clean_name).stem if "." in clean_name else clean_name
        unique_filename = f"{base_stem}_{ts}{path_obj.suffix}"
    else:
        unique_filename = f"{path_obj.stem}_{ts}{path_obj.suffix}"

    remote_movies = f"/storage/emulated/0/Movies/{unique_filename}"
    remote_downloads = f"/storage/emulated/0/Download/{unique_filename}"

    _l(f"[*] Pushing '{path_obj.name}' ({file_size_mb:.2f} MB) as '{unique_filename}' to device...")
    if stop_event and stop_event.is_set():
        raise UploadCancelledException("Upload cancelled by user.")

    res = subprocess.run([adb_exe, "-s", target, "push", str(path_obj.resolve()), remote_movies],
                         capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if res.returncode != 0:
        raise RuntimeError(f"ADB Push failed: {res.stderr}")

    run_adb(adb_exe, target, "shell", "cp", remote_movies, remote_downloads)
    run_adb(adb_exe, target, "shell", "chmod", "-R", "777", "/storage/emulated/0/Movies", "/storage/emulated/0/Download")

    _l(f"[*] Triggering media scanner for '{unique_filename}'...")
    run_adb(adb_exe, target, "shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", f"file://{remote_movies}")
    run_adb(adb_exe, target, "shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", f"file://{remote_downloads}")

    _l(f"[*] Polling MediaStore specifically for '{unique_filename}' (no stale ID fallbacks)...")
    media_id = None
    max_scan_attempts = 15
    for attempt in range(1, max_scan_attempts + 1):
        if stop_event and stop_event.is_set():
            raise UploadCancelledException("Upload cancelled by user.")
        sleep_with_control(1.0, pause_event, stop_event)

        res = run_adb(adb_exe, target, "shell", "content", "query", "--uri", "content://media/external/video/media", "--projection", "_id:_data")
        for line in reversed(res.stdout.splitlines()):
            if unique_filename in line:
                m = re.search(r"_id=(\d+)", line)
                if m:
                    media_id = m.group(1)
                    break
        if media_id:
            _l(f"[+] Found fresh indexed MediaStore ID {media_id} for '{unique_filename}' (attempt {attempt}).")
            break

        if attempt % 3 == 0:
            _l(f"[*] Re-broadcasting scanner for '{unique_filename}' (attempt {attempt}/{max_scan_attempts})...")
            run_adb(adb_exe, target, "shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", f"file://{remote_movies}")
            run_adb(adb_exe, target, "shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", f"file://{remote_downloads}")

    if not media_id:
        raise RuntimeError(f"Failed to index '{unique_filename}' in Android MediaStore after {max_scan_attempts} attempts. Aborting to avoid using stale media.")

    content_uri = f"content://media/external/video/media/{media_id}"
    _l(f"[+] Verified fresh video URI: {content_uri}")
    return content_uri


def get_installed_youtube_package(adb_exe: str, target: str) -> str:
    res = run_adb(adb_exe, target, "shell", "pm", "list", "packages")
    pkgs = res.stdout.splitlines()
    for candidate in ["app.morphe.android.youtube", "app.revanced.android.youtube", "com.google.android.youtube"]:
        if f"package:{candidate}" in pkgs:
            return candidate
    return "app.morphe.android.youtube"


def dump_ui_nodes(adb_exe: str, target: str):
    run_adb(adb_exe, target, "shell", "uiautomator", "dump", "/sdcard/window_dump.xml")
    res = run_adb(adb_exe, target, "shell", "cat", "/sdcard/window_dump.xml")
    if not res.stdout or "<hierarchy" not in res.stdout:
        run_adb(adb_exe, target, "shell", "uiautomator", "dump", "--compressed", "/sdcard/window_dump.xml")
        res = run_adb(adb_exe, target, "shell", "cat", "/sdcard/window_dump.xml")
        if not res.stdout or "<hierarchy" not in res.stdout:
            return []
    try:
        root = ET.fromstring(res.stdout)
        nodes = []
        for elem in root.iter("node"):
            bounds_str = elem.attrib.get("bounds", "")
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
            if m:
                x1, y1, x2, y2 = map(int, m.groups())
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            else:
                cx, cy = None, None
            nodes.append({
                "text": elem.attrib.get("text", ""),
                "desc": elem.attrib.get("content-desc", ""),
                "res_id": elem.attrib.get("resource-id", ""),
                "class": elem.attrib.get("class", ""),
                "cx": cx,
                "cy": cy
            })
        return nodes
    except Exception:
        return []


def find_node(nodes, text=None, desc=None, res_id=None, min_x=0, min_y=0, max_y=9999):
    for n in nodes:
        if n["cx"] is not None and n["cx"] < min_x:
            continue
        if n["cy"] is not None and (n["cy"] < min_y or n["cy"] > max_y):
            continue
        if text and text.lower() in n["text"].lower():
            return n
        if desc and desc.lower() in n["desc"].lower():
            return n
        if res_id and res_id.lower() in n["res_id"].lower():
            return n
    return None


def parse_timestamp_seconds(ts_str: str) -> float:
    """Parses timestamp strings like '1:30', '0:45', '45s', '45' into seconds."""
    ts_str = str(ts_str).strip().lower().rstrip('s')
    if ":" in ts_str:
        parts = ts_str.split(":")
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    return float(ts_str)


def input_fast_text(adb_exe: str, target: str, text: str):
    """Enters text with spaces in one single ADB command."""
    safe_text = text.replace(" ", "%s")
    safe_text = re.sub(r'([&|;$><`"\'\\])', r'\\\1', safe_text)
    run_adb(adb_exe, target, "shell", "input", "text", safe_text)


def upload_short_to_youtube(
    adb_exe: str,
    target: str,
    video_path: str,
    title: str,
    sound: Optional[str] = None,
    timestamp: Optional[str] = None,
    media_name: Optional[str] = None,
    log_fn: Optional[Callable[[str], None]] = None,
    pause_event: Optional[threading.Event] = None,
    stop_event: Optional[threading.Event] = None
):
    def _l(msg):
        if should_ignore_log(msg):
            return
        if log_fn:
            log_fn(msg)
        else:
            print(msg, flush=True)

    _l("\n========================================================")
    _l("  AUTOMATING YOUTUBE SHORT UPLOAD")
    _l("========================================================")

    yt_pkg = get_installed_youtube_package(adb_exe, target)
    _l(f"[*] Target YouTube App: {yt_pkg}")

    # 1. Fully clean emulator media & MediaStore before pushing
    clean_emulator_media(adb_exe, target, log_fn=log_fn)

    # 2. Terminate YouTube & clear stale upload drafts/sessions
    clean_youtube_upload_session(adb_exe, target, yt_pkg, log_fn=log_fn)

    # 3. Push and index video (with guaranteed unique filename & verified ID polling)
    content_uri = push_and_index_video(adb_exe, target, video_path, media_name=media_name, log_fn=log_fn, pause_event=pause_event, stop_event=stop_event)

    # 4. Ensure permissions and appops for media access
    for pkg in [yt_pkg, "app.morphe.android.youtube", "app.revanced.android.youtube"]:
        for perm in [
            "android.permission.READ_MEDIA_VIDEO",
            "android.permission.READ_MEDIA_IMAGES",
            "android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE"
        ]:
            run_adb(adb_exe, target, "shell", "pm", "grant", pkg, perm)
        for op in ["MANAGE_EXTERNAL_STORAGE", "READ_MEDIA_VIDEO", "READ_MEDIA_IMAGES", "READ_EXTERNAL_STORAGE"]:
            run_adb(adb_exe, target, "shell", "appops", "set", pkg, op, "allow")

    # 5. Launch clean YouTube instance
    _l(f"[*] Launching clean {yt_pkg}...")
    run_adb(adb_exe, target, "shell", "am", "start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", "-p", yt_pkg)
    sleep_with_control(2.5, pause_event, stop_event)

    # 6. Send Shorts upload intent to YouTube
    _l(f"[*] Sending Shorts upload intent to {yt_pkg}...")
    upload_cmd = [
        "am", "start",
        "-a", "android.intent.action.SEND",
        "-t", "video/mp4",
        "-p", yt_pkg,
        "-d", content_uri,
        "--activity-clear-top",
        "--activity-clear-task",
        "--eu", "android.intent.extra.STREAM", content_uri
    ]
    res = run_adb(adb_exe, target, "shell", *upload_cmd)
    if "Error" in res.stderr or "Exception" in res.stderr or "SecurityException" in res.stdout or "Error" in res.stdout:
        _l("[!] Elevating Shorts upload intent with root privileges...")
        run_adb(adb_exe, target, "shell", "su", "0", *upload_cmd)

    # 15-second timer to let the video editor / trimmer load
    _l("[*] Waiting 15 seconds for video editor / trimmer to load...")
    sleep_with_control(15.0, pause_event, stop_event)

    # Click Next/Done on the Trimmer screen at bottom-right (627, 1112)
    _l("[*] Advancing trimmer screen (tapping Next / Done at 627, 1112)...")
    run_adb(adb_exe, target, "shell", "input", "tap", "627", "1112")
    sleep_with_control(4.0, pause_event, stop_event)

    # Handle Sound if requested
    if sound:
        _l("[*] Adding sound from YouTube audio library...")
        # Tap Add Sound button (dynamically or fallback to top center [360, 101])
        nodes = dump_ui_nodes(adb_exe, target)
        sound_node = find_node(nodes, text="Add sound") or find_node(nodes, desc="Add sound") or find_node(nodes, text="Sound") or find_node(nodes, desc="Sound")
        if sound_node and sound_node.get("cx") and sound_node.get("cy"):
            run_adb(adb_exe, target, "shell", "input", "tap", str(sound_node["cx"]), str(sound_node["cy"]))
        else:
            run_adb(adb_exe, target, "shell", "input", "tap", "360", "101")
        sleep_with_control(2.5, pause_event, stop_event)

        if isinstance(sound, str) and sound.strip() and sound.strip().lower() not in ("true", "1"):
            search_query = sound.strip()
            _l(f"[*] Searching sound query: '{search_query}'...")
            run_adb(adb_exe, target, "shell", "input", "tap", "360", "212")
            sleep_with_control(0.8, pause_event, stop_event)
            input_fast_text(adb_exe, target, search_query)
            run_adb(adb_exe, target, "shell", "input", "keyevent", "66")  # Enter
            sleep_with_control(2.0, pause_event, stop_event)
            # Tap first result
            run_adb(adb_exe, target, "shell", "input", "tap", "360", "470")
            sleep_with_control(1.5, pause_event, stop_event)
        else:
            # Tap first popular sound
            _l("[*] Selecting top featured track...")
            run_adb(adb_exe, target, "shell", "input", "tap", "300", "460")
            sleep_with_control(1.5, pause_event, stop_event)

        # Tap attach button (bounds [608, 420][688, 500] -> cx=648, cy=460)
        _l("[+] Attaching selected sound to video...")
        run_adb(adb_exe, target, "shell", "input", "tap", "648", "460")
        sleep_with_control(2.5, pause_event, stop_event)

        # Check if error dialog appeared ("Sorry, there's an issue with this audio")
        nodes = dump_ui_nodes(adb_exe, target)
        err_node = find_node(nodes, text="issue with this audio")
        if err_node:
            _l("[!] Notice: Selected sound had a restriction/error. Dismissing dialog and selecting top standard track...")
            ok_node = find_node(nodes, text="OK")
            if ok_node and ok_node.get("cx") and ok_node.get("cy"):
                run_adb(adb_exe, target, "shell", "input", "tap", str(ok_node["cx"]), str(ok_node["cy"]))
            else:
                run_adb(adb_exe, target, "shell", "input", "tap", "640", "845")
            sleep_with_control(1.5, pause_event, stop_event)
            # Re-open sound picker and select top track
            run_adb(adb_exe, target, "shell", "input", "tap", "360", "120")
            sleep_with_control(2.0, pause_event, stop_event)
            run_adb(adb_exe, target, "shell", "input", "tap", "300", "460")
            sleep_with_control(1.5, pause_event, stop_event)
            run_adb(adb_exe, target, "shell", "input", "tap", "648", "460")
            sleep_with_control(2.5, pause_event, stop_event)
        _l("[+] Sound successfully attached to Short!")

        # Check if timestamp adjustment was requested via -t / --timestamp
        if timestamp:
            _l(f"[*] Adjusting audio starting timestamp ('{timestamp}')...")
            # Tap sound capsule in editor to open "Adjust sound" modal (top center)
            run_adb(adb_exe, target, "shell", "input", "tap", "360", "101")
            sleep_with_control(2.0, pause_event, stop_event)

            # Read exact song duration from audio adjust modal
            nodes = dump_ui_nodes(adb_exe, target)
            dur_node = find_node(nodes, res_id="audio_duration_text")
            seekbar_node = find_node(nodes, res_id="play_progress_bar")

            total_duration_sec = 158.0  # default fallback
            if dur_node and dur_node["text"]:
                try:
                    total_duration_sec = parse_timestamp_seconds(dur_node["text"])
                except Exception:
                    pass
            elif seekbar_node and seekbar_node["desc"]:
                m = re.search(r"out of (?:(\d+) minutes? )?(?:(\d+) seconds?)?", seekbar_node["desc"])
                if m:
                    mins = int(m.group(1)) if m.group(1) else 0
                    secs = int(m.group(2)) if m.group(2) else 0
                    if mins or secs:
                        total_duration_sec = float(mins * 60 + secs)

            if str(timestamp).strip().lower() in ("random", "rand", "true"):
                import random
                max_start = max(5.0, total_duration_sec - 15.0)
                target_sec = random.uniform(5.0, max_start)
                _l(f"[+] Selected random timestamp: {int(target_sec//60)}:{int(target_sec%60):02d} ({target_sec:.1f}s / {total_duration_sec:.1f}s)")
            else:
                try:
                    target_sec = parse_timestamp_seconds(str(timestamp))
                except Exception:
                    target_sec = 10.0
                _l(f"[+] Target audio timestamp: {int(target_sec//60)}:{int(target_sec%60):02d} ({target_sec:.1f}s / {total_duration_sec:.1f}s)")

            # Stage 1: Coarse seek on seekbar (x=96 to x=624, width=528)
            track_left = 96
            track_right = 624
            usable_width = track_right - track_left

            ratio = min(1.0, max(0.0, target_sec / max(1.0, total_duration_sec)))
            tap_x = int(track_left + ratio * usable_width)
            _l(f"[*] Coarse seek to position on scrubber at ({tap_x}, 832)...")
            run_adb(adb_exe, target, "shell", "input", "tap", str(tap_x), "832")
            sleep_with_control(1.2, pause_event, stop_event)

            # Stage 2: Precision continuous micro-adjustment on waveform (y=960, ~100px per second)
            for step in range(5):
                if stop_event and stop_event.is_set():
                    raise UploadCancelledException("Upload cancelled by user.")
                nodes = dump_ui_nodes(adb_exe, target)
                pos_node = find_node(nodes, res_id="play_position_text")
                curr_sec = parse_timestamp_seconds(pos_node["text"]) if pos_node and pos_node["text"] else target_sec
                diff_sec = target_sec - curr_sec

                if abs(diff_sec) < 0.5:
                    _l(f"[+] Exact target timestamp reached: {pos_node['text'] if pos_node else ''} ({curr_sec:.1f}s)!")
                    break

                swipe_dx = int(diff_sec * 100)
                swipe_dx = max(-350, min(350, swipe_dx))
                start_x = 360
                end_x = start_x - swipe_dx
                _l(f"[*] Micro-adjusting waveform ({pos_node.get('text', '') if pos_node else ''} -> target, diff {diff_sec:+.1f}s)...")
                run_adb(adb_exe, target, "shell", "input", "swipe", str(start_x), "960", str(end_x), "960", "250")
                sleep_with_control(1.0, pause_event, stop_event)

            # Tap 'Done' button at (632, 1112)
            run_adb(adb_exe, target, "shell", "input", "tap", "632", "1112")
            sleep_with_control(1.5, pause_event, stop_event)
            _l("[+] Audio timestamp adjusted and applied successfully!")

    # Advance from Shorts Editor to Details / Metadata screen
    _l("[*] Advancing to Details screen (tapping Next at 550, 1124)...")
    run_adb(adb_exe, target, "shell", "input", "tap", "550", "1124")
    _l("[*] Waiting 15 seconds for Details / Metadata screen to load...")
    sleep_with_control(15.0, pause_event, stop_event)

    # 5. Metadata / Caption input
    _l(f"[*] Setting title: '{title}'...")
    nodes = dump_ui_nodes(adb_exe, target)
    title_node = find_node(nodes, text="Create a title") or find_node(nodes, text="Caption") or find_node(nodes, res_id="title")
    if title_node and title_node.get("cx") and title_node.get("cy"):
        run_adb(adb_exe, target, "shell", "input", "tap", str(title_node["cx"]), str(title_node["cy"]))
    else:
        run_adb(adb_exe, target, "shell", "input", "tap", "450", "170")
    sleep_with_control(1.2, pause_event, stop_event)
    input_fast_text(adb_exe, target, title)
    sleep_with_control(1.2, pause_event, stop_event)

    # Dismiss keyboard
    _l("[*] Dismissing keyboard...")
    run_adb(adb_exe, target, "shell", "input", "keyevent", "4")
    sleep_with_control(1.5, pause_event, stop_event)

    # Tap Upload Short / Upload button
    _l("[+] Tapping Upload button...")
    nodes = dump_ui_nodes(adb_exe, target)
    upload_btn = (
        find_node(nodes, text="Upload Short")
        or find_node(nodes, desc="Upload Short")
        or find_node(nodes, text="Upload")
        or find_node(nodes, desc="Upload")
        or find_node(nodes, res_id="upload_bottom_button")
    )
    if upload_btn and upload_btn.get("cx") and upload_btn.get("cy"):
        run_adb(adb_exe, target, "shell", "input", "tap", str(upload_btn["cx"]), str(upload_btn["cy"]))
    else:
        run_adb(adb_exe, target, "shell", "input", "tap", "360", "1120")
    sleep_with_control(2.5, pause_event, stop_event)

    _l("\n[+] YouTube Short upload submitted successfully!")
    _l("[*] Video is now uploading and processing on your channel.")


def main():
    parser = argparse.ArgumentParser(description="Upload YouTube Shorts directly to an Android container channel.")
    parser.add_argument("video_path", nargs="?", default=None, help="Path to the video file (.mp4)")
    parser.add_argument("-u", "--upload", nargs="?", const=True, default=None, help="Upload flag or path to video file")
    parser.add_argument("-v", "--view", action="store_true", help="Launch scrcpy to view the screen live")
    parser.add_argument("-s", "--sound", nargs="?", const=True, default=None, help="Select audio from YouTube music library (optional query)")
    parser.add_argument("-t", "--timestamp", nargs="?", const="random", default=None, help="Starting timestamp for sound (e.g. -t '0:30', -t '1:15', -t 45, or -t / -t random)")
    parser.add_argument("-a", "--account", default="01", help="Redroid account number (e.g. 01, 02). Default: 01")
    parser.add_argument("--title", "-T", default=None, help="Title for the YouTube Short")
    parser.add_argument("-n", "-m", "--name", "--media-name", dest="media_name", default=None, help="Custom filename to set for the video inside Android (e.g. -n xyz, -m xyz)")
    parser.add_argument("-c", "--clean", action="store_true", help="Clean all emulator media, reset MediaStore, clear YouTube upload drafts, and exit")
    parser.add_argument("--adb", default=None, help="Custom path to adb executable")
    parser.add_argument("--scrcpy", default=None, help="Custom path to scrcpy executable")

    args = parser.parse_args()

    if args.clean:
        adb_exe = args.adb or find_tool("adb", DEFAULT_ADB)
        account_num = int(args.account)
        target = connect_adb(adb_exe, f"127.0.0.1:{5800 + account_num}")
        yt_pkg = get_installed_youtube_package(adb_exe, target)
        clean_emulator_media(adb_exe, target)
        clean_youtube_upload_session(adb_exe, target, yt_pkg)
        print("[SUCCESS] Emulator media storage, MediaStore, and YouTube upload session cleaned successfully!", flush=True)
        sys.exit(0)

    video_file = None
    if isinstance(args.upload, str):
        video_file = args.upload
    elif args.video_path:
        video_file = args.video_path

    if not video_file and not args.upload:
        parser.print_help()
        sys.exit(1)

    if not video_file:
        print("[!] Error: Please specify a video file path to upload.", flush=True)
        sys.exit(1)

    adb_exe = args.adb or find_tool("adb", DEFAULT_ADB)
    scrcpy_exe = args.scrcpy or find_tool("scrcpy", DEFAULT_SCRCPY)

    account_num = int(args.account)
    host_port = 5800 + account_num
    target = f"127.0.0.1:{host_port}"
    short_title = args.title or Path(video_file).stem

    sound_arg = args.sound
    if args.timestamp and sound_arg is None:
        sound_arg = True

    print("========================================================", flush=True)
    print(f"  REDROID YOUTUBE SHORT UPLOADER (Account {args.account})", flush=True)
    print(f"  Video:      {video_file}", flush=True)
    print(f"  Media Name: {args.media_name if args.media_name else 'Auto-generated'}", flush=True)
    print(f"  Title:      {short_title}", flush=True)
    print(f"  Sound:      {sound_arg if sound_arg is not None else 'None'}", flush=True)
    print(f"  Timestamp:  {args.timestamp if args.timestamp is not None else 'Default'}", flush=True)
    print(f"  Target:     {target}", flush=True)
    print("========================================================", flush=True)

    target = connect_adb(adb_exe, target)

    if args.view:
        launch_scrcpy(scrcpy_exe, target)

    upload_short_to_youtube(adb_exe, target, video_file, short_title, sound=sound_arg, timestamp=args.timestamp, media_name=args.media_name)
    print(f"\n[SUCCESS] YouTube Short '{short_title}' uploaded successfully!", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()

