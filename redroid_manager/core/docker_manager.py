import os
import platform
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from .config_manager import is_port_available, DATA_ROOT

import time

IS_WINDOWS = platform.system() == "Windows"


def run_cmd(args: list, check: bool = False, timeout: int = 15) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=check,
            timeout=timeout
        )
    except Exception as e:
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr=str(e))


import shlex

def run_docker(*docker_args: str) -> subprocess.CompletedProcess:
    if IS_WINDOWS:
        cmd_str = "docker " + " ".join(shlex.quote(str(a)) for a in docker_args)
        wsl_cmd = ["wsl.exe", "-d", "Ubuntu", "-u", "root", "--exec", "/bin/bash", "-c", cmd_str]
        return run_cmd(wsl_cmd, timeout=8)

    res = run_cmd(["docker", *docker_args], timeout=5)
    if res.returncode == 0:
        return res

    cmd_str = "docker " + " ".join(shlex.quote(str(a)) for a in docker_args)
    wsl_cmd = ["wsl", "-d", "Ubuntu", "-u", "root", "--exec", "/bin/bash", "-c", cmd_str]
    return run_cmd(wsl_cmd, timeout=8)


def ensure_docker_daemon(timeout: int = 30) -> bool:
    """Verifies Docker engine readiness inside WSL or Host, auto-starting if offline."""
    res = run_docker("ps")
    if res.returncode == 0:
        return True

    if IS_WINDOWS:
        run_cmd(["wsl.exe", "-d", "Ubuntu", "-u", "root", "--exec", "bash", "-c", "systemctl start docker || service docker start"], timeout=10)
        time.sleep(2)
        res = run_docker("ps")
        if res.returncode == 0:
            return True

    start_time = time.time()
    while time.time() - start_time < timeout:
        time.sleep(2)
        res = run_docker("ps")
        if res.returncode == 0:
            return True

    return False


REDROID_PS1 = Path(__file__).resolve().parent.parent.parent / "ytuploader" / "redroid.ps1"


class DockerManager:
    def __init__(self, base_image: str = "redroid-instagram:ndk"):
        self.base_image = base_image

    def ensure_image_available(self, image: Optional[str] = None) -> bool:
        target_img = image or self.base_image
        res = run_docker("images", "-q", target_img)
        if res.returncode == 0 and res.stdout.strip():
            return True
        pull_res = run_docker("pull", target_img)
        return pull_res.returncode == 0

    def get_container_status(self, container_name: str) -> str:
        res = run_docker("ps", "-a", "--filter", f"name=^/{container_name}$", "--format", "{{.State}}")
        if res.returncode != 0 or not res.stdout.strip():
            return "not_found"
        state = res.stdout.strip().lower()
        if state == "running":
            return "running"
        elif state in ["exited", "created", "paused", "dead"]:
            return "stopped"
        return state

    def get_container_logs(self, container_name: str, tail: int = 60) -> str:
        res = run_docker("logs", "--tail", str(tail), container_name)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
        if "timed out" in res.stderr.lower():
            return "[Container console output idle. Redroid streams OS activity via Android logcat]"
        return res.stderr.strip() or "[No container console logs available]"

    def get_all_container_statuses(self) -> Dict[str, str]:
        res = run_docker("ps", "-a", "--format", "{{.Names}} {{.State}}")
        statuses = {}
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.strip().splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    name, state = parts[0].strip(), parts[1].strip().lower()
                    statuses[name] = "running" if state == "running" else "stopped"
        return statuses

    def get_container_stats(self, container_name: str) -> Dict[str, Any]:
        res = run_docker("stats", "--no-stream", "--format", "{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}", container_name)
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split("\t")
            if len(parts) >= 3:
                return {
                    "memory_usage": parts[0],
                    "memory_percent": parts[1],
                    "cpu_percent": parts[2]
                }
        return {"memory_usage": "0B", "memory_percent": "0%", "cpu_percent": "0%"}

    def start_container(self, brand: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
        if not ensure_docker_daemon():
            return False, "Docker Engine / Docker Desktop is not running. Please ensure Docker Desktop is open."

        container_name = brand["container_name"]
        host_port = brand["host_port"]
        brand_id = brand["brand_id"]

        status = self.get_container_status(container_name)
        if status == "running":
            return True, f"Container '{container_name}' is already running."

        # Connect .\ytuploader\redroid.ps1 start <container_name>
        if IS_WINDOWS and REDROID_PS1.exists():
            try:
                ps_cmd = [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-File", str(REDROID_PS1),
                    "start", container_name
                ]
                res = subprocess.run(ps_cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
                if res.returncode == 0:
                    return True, f"Container '{container_name}' started successfully via redroid.ps1 on port {host_port}."
                else:
                    err_msg = (res.stderr.strip() or res.stdout.strip())
                    print(f"[DockerManager] redroid.ps1 error: {err_msg}")
            except Exception as e:
                print(f"[DockerManager] Exception running redroid.ps1: {e}")

        # Fallback if redroid.ps1 is not available or failed
        if status == "stopped":
            start_res = run_docker("start", container_name)
            if start_res.returncode == 0:
                return True, f"Container '{container_name}' started successfully."
            return False, f"Failed to start existing container: {start_res.stderr.strip()}"

        cfg = settings or {}
        image = cfg.get("base_image", self.base_image)
        memory_limit = cfg.get("memory_limit", "1800m")
        fps = str(cfg.get("default_fps", 30))
        dpi = str(cfg.get("default_dpi", 320))
        res_str = cfg.get("default_resolution", "720x1280")
        width, height = res_str.split("x") if "x" in res_str else ("720", "1280")

        # Native Docker named volume (EXT4 in WSL2 - never mount Windows NTFS as /data)
        volume_name = f"{container_name}-data"
        run_docker("volume", "create", volume_name)

        # Clone master template (redroid-account-01-data) with all apps & settings into the new brand volume
        if IS_WINDOWS and volume_name != "redroid-account-01-data":
            run_cmd([
                "wsl.exe", "-d", "Ubuntu", "-u", "root", "--exec", "bash", "-c",
                f"[ -d /var/lib/docker/volumes/redroid-account-01-data/_data ] && cp -au /var/lib/docker/volumes/redroid-account-01-data/_data/. /var/lib/docker/volumes/{volume_name}/_data/"
            ], timeout=60)

        snd_args = []
        if IS_WINDOWS:
            has_snd = run_cmd(["wsl.exe", "-d", "Ubuntu", "-u", "root", "--exec", "bash", "-c", "[ -d /dev/snd ] && echo HAS_SND"], timeout=5).stdout.strip()
            if "HAS_SND" in has_snd:
                run_cmd(["wsl.exe", "-d", "Ubuntu", "-u", "root", "--exec", "chmod", "-R", "666", "/dev/snd"], timeout=5)
                snd_args = ["--device", "/dev/snd", "-v", "/dev/snd:/dev/snd"]

        docker_run_args = [
            "run", "-d",
            "--name", container_name,
            "--restart", "always",
            f"--memory={memory_limit}",
            f"--memory-swap={memory_limit}",
            "--privileged"
        ] + snd_args + [
            "-v", f"{volume_name}:/data",
            "-p", f"{host_port}:5555",
            image,
            f"androidboot.redroid_width={width}",
            f"androidboot.redroid_height={height}",
            f"androidboot.redroid_dpi={dpi}",
            f"androidboot.redroid_fps={fps}",
            "androidboot.redroid_gpu_mode=guest",
            "androidboot.use_memfd=1",
            "androidboot.selinux=permissive",
            "ro.dalvik.vm.native.bridge=libndk_translation.so",
            "ro.enable.native.bridge.exec=1",
            "ro.product.cpu.abilist=x86_64,arm64-v8a,x86,armeabi-v7a,armeabi",
            "ro.product.cpu.abilist32=x86,armeabi-v7a,armeabi",
            "ro.product.cpu.abilist64=x86_64,arm64-v8a",
            "ro.dalvik.vm.isa.arm=x86",
            "ro.dalvik.vm.isa.arm64=x86_64",
            "ro.product.brand=google",
            "ro.product.model=Pixel 8 Pro",
            "ro.product.name=husky",
            "ro.product.device=husky",
            "ro.product.manufacturer=Google",
            "ro.build.fingerprint=google/husky/husky:14/UD1A.230803.041/10808477:user/release-keys",
            "ro.build.type=user",
            "ro.build.tags=release-keys"
        ]

        run_res = run_docker(*docker_run_args)
        if run_res.returncode == 0:
            return True, f"Container '{container_name}' created and started on port {host_port}."
        return False, f"Docker run failed: {run_res.stderr.strip()}"

    def stop_container(self, container_name: str) -> Tuple[bool, str]:
        status = self.get_container_status(container_name)
        if status not in ["running"]:
            return True, f"Container '{container_name}' is already stopped."

        if IS_WINDOWS and REDROID_PS1.exists():
            try:
                ps_cmd = [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-File", str(REDROID_PS1),
                    "stop", container_name
                ]
                res = subprocess.run(ps_cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
                if res.returncode == 0:
                    return True, f"Container '{container_name}' stopped via redroid.ps1."
            except Exception as e:
                print(f"[DockerManager] stop redroid.ps1 failed: {e}")

        res = run_docker("stop", container_name)
        if res.returncode == 0:
            return True, f"Container '{container_name}' stopped."
        return False, f"Failed to stop container: {res.stderr.strip()}"

    def remove_container(self, container_name: str, force: bool = True) -> Tuple[bool, str]:
        args = ["rm"]
        if force:
            args.append("-f")
        args.append(container_name)
        res = run_docker(*args)
        if res.returncode == 0:
            return True, f"Container '{container_name}' removed."
        return False, f"Failed to remove container: {res.stderr.strip()}"


docker_manager = DockerManager()
