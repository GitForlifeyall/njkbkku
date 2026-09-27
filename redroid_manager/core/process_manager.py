import asyncio
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from .adb_manager import find_tool

IS_WINDOWS = platform.system() == "Windows"


class ProcessManager:
    def __init__(self):
        self.scrcpy_path = find_tool("scrcpy")
        self.active_scrcpy: Dict[str, subprocess.Popen] = {}
        self.active_uploads: Dict[str, Dict[str, Any]] = {}
        self.log_queues: Dict[str, Set[asyncio.Queue]] = {}
        self.brand_logs: Dict[str, List[str]] = {}
        self.boot_logs: Dict[str, List[str]] = {}

    def record_boot_log(self, brand_id: str, line: str):
        if brand_id not in self.boot_logs:
            self.boot_logs[brand_id] = []
        self.boot_logs[brand_id].append(line)
        if len(self.boot_logs[brand_id]) > 500:
            self.boot_logs[brand_id].pop(0)

    def get_boot_logs(self, brand_id: str) -> List[str]:
        return list(self.boot_logs.get(brand_id, []))

    def launch_scrcpy(self, brand: Dict[str, Any]) -> Tuple[bool, str]:
        brand_id = brand["brand_id"]
        brand_name = brand.get("name", brand_id)
        host_port = brand["host_port"]
        target = f"127.0.0.1:{host_port}"

        # Ensure adb connects first with offline detection
        adb_exe = find_tool("adb")
        try:
            dev_res = subprocess.run([adb_exe, "devices"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=4)
            if target in dev_res.stdout and "offline" in dev_res.stdout:
                subprocess.run([adb_exe, "disconnect", target], stdin=subprocess.DEVNULL, capture_output=True, timeout=3)
            subprocess.run([adb_exe, "connect", target], stdin=subprocess.DEVNULL, capture_output=True, timeout=5)
        except Exception:
            pass

        existing = self.active_scrcpy.get(brand_id)
        if existing and existing.poll() is None:
            return True, f"Scrcpy session for '{brand_name}' is already active."

        cmd = [
            self.scrcpy_path,
            "-s", target,
            "--force-adb-forward",
            "--video-codec=h264",
            "--video-encoder=OMX.google.h264.encoder",
            "--window-title", f"Redroid - {brand_name} ({target})",
            "--no-audio",
            "--video-bit-rate=4M",
            "--max-fps=30",
            "--stay-awake"
        ]

        try:
            creation_flags = 0
            if IS_WINDOWS:
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags if IS_WINDOWS else 0,
                start_new_session=True if not IS_WINDOWS else False
            )
            import time
            time.sleep(0.4)
            if proc.poll() is not None:
                # If exited immediately, retry without fixed encoder
                fallback_cmd = [
                    self.scrcpy_path,
                    "-s", target,
                    "--force-adb-forward",
                    "--window-title", f"Redroid - {brand_name} ({target})",
                    "--no-audio",
                    "--video-bit-rate=4M",
                    "--max-fps=30",
                    "--stay-awake"
                ]
                proc = subprocess.Popen(
                    fallback_cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags if IS_WINDOWS else 0,
                    start_new_session=True if not IS_WINDOWS else False
                )
            self.active_scrcpy[brand_id] = proc
            return True, f"Launched live Scrcpy window for '{brand_name}'."
        except Exception as e:
            return False, f"Failed to launch scrcpy: {str(e)}"

    def get_recent_logs(self, brand_id: str) -> List[str]:
        return list(self.brand_logs.get(brand_id, []))

    def is_scrcpy_active(self, brand_id: str) -> bool:
        proc = self.active_scrcpy.get(brand_id)
        if proc and proc.poll() is None:
            return True
        return False

    def get_log_queue(self, brand_id: str) -> asyncio.Queue:
        if brand_id not in self.log_queues:
            self.log_queues[brand_id] = set()
        q = asyncio.Queue(maxsize=500)
        self.log_queues[brand_id].add(q)
        return q

    def unsubscribe_log_queue(self, brand_id: str, queue: asyncio.Queue):
        if brand_id in self.log_queues:
            self.log_queues[brand_id].discard(queue)
            if not self.log_queues[brand_id]:
                del self.log_queues[brand_id]

    async def broadcast_log(self, brand_id: str, line: str):
        if brand_id not in self.brand_logs:
            self.brand_logs[brand_id] = []
        self.brand_logs[brand_id].append(line)
        if len(self.brand_logs[brand_id]) > 300:
            self.brand_logs[brand_id].pop(0)

        if brand_id in self.log_queues:
            for q in list(self.log_queues[brand_id]):
                try:
                    q.put_nowait(line)
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()
                        q.put_nowait(line)
                    except Exception:
                        pass

    async def run_upload_task(
        self,
        brand: Dict[str, Any],
        video_path: Optional[str] = None,
        title: Optional[str] = None,
        sound: Optional[str] = None,
        timestamp: Optional[str] = None
    ) -> bool:
        brand_id = brand["brand_id"]
        host_port = brand["host_port"]
        target = f"127.0.0.1:{host_port}"

        upload_script = Path(__file__).resolve().parent.parent / "uploadshort.py"
        python_exe = sys.executable

        cmd = [
            python_exe,
            "-u",
            str(upload_script),
            "--device", target,
            "--brand", brand_id
        ]

        if video_path:
            cmd.extend(["--video", video_path])
        if title:
            cmd.extend(["--title", title])
        if sound:
            cmd.extend(["--sound", sound])
        if timestamp:
            cmd.extend(["--timestamp", timestamp])

        self.active_uploads[brand_id] = {
            "status": "running",
            "start_time": asyncio.get_event_loop().time(),
            "logs": [],
            "process": None,
            "brand": brand
        }

        await self.broadcast_log(brand_id, f"[SYSTEM] Launching upload job for {brand['name']} ({target})...\n")
        await self.broadcast_log(brand_id, f"[SYSTEM] Command: {' '.join(cmd)}\n")

        loop = asyncio.get_running_loop()

        def _worker():
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1
                )
                if brand_id in self.active_uploads:
                    self.active_uploads[brand_id]["process"] = proc

                for line in iter(proc.stdout.readline, ''):
                    if brand_id in self.active_uploads:
                        self.active_uploads[brand_id]["logs"].append(line)
                    asyncio.run_coroutine_threadsafe(
                        self.broadcast_log(brand_id, line),
                        loop
                    )
                proc.stdout.close()
                return proc.wait()
            except Exception as e:
                err = f"\n[ERROR] Exception executing upload worker ({type(e).__name__}): {e}\n"
                if brand_id in self.active_uploads:
                    self.active_uploads[brand_id]["logs"].append(err)
                asyncio.run_coroutine_threadsafe(
                    self.broadcast_log(brand_id, err),
                    loop
                )
                return 1

        try:
            exit_code = await asyncio.to_thread(_worker)
            cur_status = self.active_uploads.get(brand_id, {}).get("status")
            if cur_status == "stopped":
                await self.broadcast_log(brand_id, f"\n[SYSTEM] 🛑 Upload job was stopped by user.\n")
                return False

            success = (exit_code == 0)
            status_str = "completed" if success else f"failed (code {exit_code})"
            if brand_id in self.active_uploads:
                self.active_uploads[brand_id]["status"] = status_str
            await self.broadcast_log(brand_id, f"\n[SYSTEM] Upload job {status_str}.\n")
            return success
        except Exception as e:
            err_msg = f"\n[ERROR] Exception executing upload worker ({type(e).__name__}): {str(e)}\n"
            if brand_id in self.active_uploads:
                self.active_uploads[brand_id]["status"] = "error"
            await self.broadcast_log(brand_id, err_msg)
            return False
        finally:
            import tempfile
            pause_flag = Path(tempfile.gettempdir()) / f"redroid_pause_{brand_id}.flag"
            if pause_flag.exists():
                try:
                    pause_flag.unlink()
                except Exception:
                    pass

    def is_upload_active(self, brand_id: str) -> bool:
        info = self.active_uploads.get(brand_id)
        if not info:
            return False
        if info.get("status") == "running":
            proc = info.get("process")
            if proc is not None and proc.poll() is not None:
                info["status"] = "finished"
                return False
            return True
        return False

    def is_upload_paused(self, brand_id: str) -> bool:
        if not self.is_upload_active(brand_id):
            return False
        import tempfile
        pause_flag = Path(tempfile.gettempdir()) / f"redroid_pause_{brand_id}.flag"
        return pause_flag.exists()

    def toggle_pause_upload(self, brand_id: str) -> Tuple[bool, bool, str]:
        """
        Toggles pause state for brand upload job.
        Returns: (success: bool, is_now_paused: bool, message: str)
        """
        if not self.is_upload_active(brand_id):
            return False, False, "No active upload job running for this brand."

        import tempfile
        pause_flag = Path(tempfile.gettempdir()) / f"redroid_pause_{brand_id}.flag"

        if pause_flag.exists():
            try:
                pause_flag.unlink()
            except Exception as e:
                return False, True, f"Failed to resume upload: {e}"
            msg = "\n[SYSTEM] ▶ Upload RESUMED by user.\n"
            is_now_paused = False
        else:
            try:
                pause_flag.touch()
            except Exception as e:
                return False, False, f"Failed to pause upload: {e}"
            msg = "\n[SYSTEM] ⏸ Upload PAUSED by user. Automation frozen.\n"
            is_now_paused = True

        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(
                self.broadcast_log(brand_id, msg),
                loop
            )
        except Exception:
            if brand_id in self.brand_logs:
                self.brand_logs[brand_id].append(msg)

        return True, is_now_paused, f"Upload {'paused' if is_now_paused else 'resumed'} successfully."

    def stop_upload_task(self, brand_id: str) -> Tuple[bool, str]:
        upload_info = self.active_uploads.get(brand_id)
        if not upload_info:
            return False, "No active upload job found for this brand."

        # Clean up pause flag if present
        import tempfile
        pause_flag = Path(tempfile.gettempdir()) / f"redroid_pause_{brand_id}.flag"
        if pause_flag.exists():
            try:
                pause_flag.unlink()
            except Exception:
                pass

        proc: Optional[subprocess.Popen] = upload_info.get("process")
        upload_info["status"] = "stopped"

        # 1. Kill the local python subprocess tree immediately
        if proc and proc.poll() is None:
            try:
                if IS_WINDOWS:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL, capture_output=True, timeout=5)
                else:
                    proc.kill()
            except Exception as e:
                try:
                    proc.kill()
                except Exception:
                    pass

        # 2. Reset the Android container to dismiss the YouTube editor
        brand = upload_info.get("brand")
        if brand:
            host_port = brand["host_port"]
            target = f"127.0.0.1:{host_port}"
            adb_exe = find_tool("adb")
            try:
                subprocess.run([adb_exe, "-s", target, "shell", "am", "force-stop", "app.morphe.android.youtube"], stdin=subprocess.DEVNULL, capture_output=True, timeout=3)
                subprocess.run([adb_exe, "-s", target, "shell", "am", "force-stop", "com.google.android.apps.youtube.app"], stdin=subprocess.DEVNULL, capture_output=True, timeout=3)
                subprocess.run([adb_exe, "-s", target, "shell", "input", "keyevent", "3"], stdin=subprocess.DEVNULL, capture_output=True, timeout=2) # HOME
            except Exception:
                pass

        # 3. Log event
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(
                self.broadcast_log(brand_id, "\n[SYSTEM] 🛑 Upload script was TERMINATED IMMEDIATELY by user request. Emulator reset.\n"),
                loop
            )
        except Exception:
            if brand_id in self.brand_logs:
                self.brand_logs[brand_id].append("\n[SYSTEM] 🛑 Upload script was TERMINATED IMMEDIATELY by user request.\n")

        return True, "Upload script stopped immediately."


process_manager = ProcessManager()

