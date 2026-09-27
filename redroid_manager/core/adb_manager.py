import asyncio
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Tuple, Optional, Dict


def find_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    winget_packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    if winget_packages.exists():
        try:
            for p in winget_packages.glob(f"**/{name}.exe"):
                if p.is_file():
                    return str(p)
        except Exception:
            pass

    common_paths = [
        Path(local_app_data) / "Programs" / "scrcpy" / f"{name}.exe",
        Path(r"C:\tools\scrcpy") / f"{name}.exe",
        Path(r"C:\platform-tools") / f"{name}.exe",
        Path(local_app_data) / "Android" / "Sdk" / "platform-tools" / f"{name}.exe",
    ]
    for p in common_paths:
        if p.exists():
            return str(p)
    return name


class AdbManager:
    def __init__(self, adb_path: Optional[str] = None):
        self.adb_path = adb_path or find_tool("adb")

    def run_adb(self, target: Optional[str], *args: str, timeout: int = 15) -> subprocess.CompletedProcess:
        cmd = [self.adb_path]
        if target:
            cmd.extend(["-s", target])
        cmd.extend(list(args))
        try:
            return subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout
            )
        except Exception as e:
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr=str(e))

    def get_devices(self) -> Dict[str, str]:
        res = self.run_adb(None, "devices", timeout=5)
        devices: Dict[str, str] = {}
        if res.returncode == 0 and res.stdout:
            for line in res.stdout.strip().splitlines()[1:]:
                parts = line.strip().split()
                if len(parts) >= 2:
                    devices[parts[0]] = parts[1]
        return devices

    def connect(self, host_port: int, host: str = "127.0.0.1", timeout: int = 3) -> Tuple[bool, str]:
        target = f"{host}:{host_port}"
        devices = self.get_devices()
        
        # If listed as offline or unauthorized, clear stale socket state first
        if devices.get(target) in ["offline", "unauthorized"]:
            self.disconnect(host_port, host)
            devices = self.get_devices()

        if devices.get(target) == "device":
            return True, f"Connected to {target}"
        if host_port == 5555 and devices.get("emulator-5554") == "device":
            return True, f"Connected to {target} (aliased as emulator-5554)"

        res = self.run_adb(None, "connect", target, timeout=timeout)
        out = (res.stdout.strip() + " " + res.stderr.strip()).strip()
        
        # Re-verify device state
        devices_after = self.get_devices()
        if devices_after.get(target) == "device":
            return True, f"Connected to {target}"
        if host_port == 5555 and devices_after.get("emulator-5554") == "device":
            return True, f"Connected to {target} (aliased as emulator-5554)"

        if "connected to" in out.lower() or "already connected" in out.lower():
            return True, f"Connected to {target}"
        return False, out

    def disconnect(self, host_port: int, host: str = "127.0.0.1") -> bool:
        target = f"{host}:{host_port}"
        res = self.run_adb(None, "disconnect", target, timeout=3)
        if host_port == 5555:
            self.run_adb(None, "disconnect", "emulator-5554", timeout=2)
        return res.returncode == 0

    def is_boot_completed(self, host_port: int, host: str = "127.0.0.1") -> bool:
        target = f"{host}:{host_port}"
        devices = self.get_devices()
        dev_state = devices.get(target) or (devices.get("emulator-5554") if host_port == 5555 else None)
        
        if dev_state != "device":
            self.connect(host_port, host, timeout=2)

        # Check target directly
        res1 = self.run_adb(target, "shell", "getprop", "sys.boot_completed", timeout=2)
        if res1.returncode == 0 and res1.stdout.strip() == "1":
            return True

        res2 = self.run_adb(target, "shell", "getprop", "dev.bootcomplete", timeout=2)
        if res2.returncode == 0 and res2.stdout.strip() == "1":
            return True

        # For default 5555, also check emulator-5554 alias if needed
        if host_port == 5555:
            res_alias = self.run_adb("emulator-5554", "shell", "getprop", "sys.boot_completed", timeout=2)
            if res_alias.returncode == 0 and res_alias.stdout.strip() == "1":
                return True

        # If device returned "device offline", trigger auto-recovery
        if "device offline" in (res1.stderr + res2.stderr):
            self.disconnect(host_port, host)

        return False

    async def wait_for_boot(self, host_port: int, host: str = "127.0.0.1", timeout_sec: int = 60, poll_interval: float = 1.5) -> bool:
        start_time = time.time()
        self.connect(host_port, host)

        while time.time() - start_time < timeout_sec:
            if self.is_boot_completed(host_port, host):
                return True
            await asyncio.sleep(poll_interval)
            self.connect(host_port, host)
            
        return False

    def get_device_status(self, host_port: int, host: str = "127.0.0.1") -> str:
        target = f"{host}:{host_port}"
        self.connect(host_port, host)
        if self.is_boot_completed(host_port, host):
            return "READY"
        
        devices = self.get_devices()
        if target in devices or (host_port == 5555 and "emulator-5554" in devices):
            dev_state = devices.get(target) or devices.get("emulator-5554")
            if dev_state == "device":
                return "BOOTING"
            return "OFFLINE"
        return "OFFLINE"


adb_manager = AdbManager()
