import asyncio
import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from core.config_manager import config_manager
from core.docker_manager import docker_manager
from core.adb_manager import adb_manager
from core.process_manager import process_manager

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Redroid Multi-Instance Manager", version="1.0.0")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

brand_states: Dict[str, str] = {}
cached_brand_states: Dict[str, str] = {}


class BrandCreateRequest(BaseModel):
    name: str
    brand_id: Optional[str] = None


class UploadRequest(BaseModel):
    video_path: Optional[str] = None
    title: Optional[str] = None
    sound: Optional[str] = None
    timestamp: Optional[str] = None


@app.on_event("startup")
async def startup_event():
    # Start background task to keep WSL2 and Docker continuously alive on Windows
    asyncio.create_task(_wsl_keepalive_loop())
    # Start continuous background scanner to keep status cache updated non-blocking
    asyncio.create_task(_status_scanner_loop())


async def _wsl_keepalive_loop():
    while True:
        try:
            if os.name == "nt":
                await asyncio.to_thread(
                    subprocess.run,
                    ["wsl.exe", "-d", "Ubuntu", "-u", "root", "--exec", "/bin/bash", "-c", "service docker status >/dev/null 2>&1 || service docker start >/dev/null 2>&1"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
        except Exception:
            pass
        await asyncio.sleep(25)


async def _status_scanner_loop():
    """Background worker that refreshes Docker container and ADB states asynchronously."""
    while True:
        try:
            brands = config_manager.get_all_brands()
            statuses = await asyncio.to_thread(docker_manager.get_all_container_statuses)
            
            for b in brands:
                c_name = b.get("container_name")
                b_id = b.get("brand_id")
                port = b.get("host_port")
                
                c_status = statuses.get(c_name, "not_found")
                if c_status != "running":
                    cached_brand_states[b_id] = "STOPPED"
                    brand_states[b_id] = "STOPPED"
                else:
                    # If currently booting in background, let start task manage state or check adb
                    is_boot = await asyncio.to_thread(adb_manager.is_boot_completed, port)
                    if is_boot:
                        cached_brand_states[b_id] = "READY"
                        brand_states[b_id] = "READY"
                    else:
                        current = cached_brand_states.get(b_id, "BOOTING")
                        cached_brand_states[b_id] = "BOOTING" if current != "STOPPED" else "STOPPED"
        except Exception:
            pass
        await asyncio.sleep(5)


def resolve_brand_state(brand: Dict[str, Any]) -> str:
    brand_id = brand["brand_id"]
    state = cached_brand_states.get(brand_id, brand_states.get(brand_id, "STOPPED"))
    if state == "READY":
        if brand_id in process_manager.active_uploads and process_manager.active_uploads[brand_id].get("status") == "running":
            return "BUSY"
        if process_manager.is_scrcpy_active(brand_id):
            return "BUSY"
    return state


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/brands")
def list_brands():
    brands = config_manager.get_all_brands()
    enriched = []
    for b in brands:
        brand_id = b["brand_id"]
        state = resolve_brand_state(b)
        enriched.append({
            **b,
            "state": state,
            "memory_usage": "0B",
            "memory_percent": "0%",
            "is_scrcpy_open": process_manager.is_scrcpy_active(brand_id),
            "is_uploading": process_manager.is_upload_active(brand_id),
            "is_upload_paused": process_manager.is_upload_paused(brand_id)
        })
    return JSONResponse(enriched)


@app.post("/api/brands")
def create_brand(req: BrandCreateRequest):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Brand name cannot be empty.")
    new_brand = config_manager.add_brand(name=req.name, brand_id=req.brand_id)
    brand_states[new_brand["brand_id"]] = "STOPPED"
    return JSONResponse(new_brand, status_code=201)


@app.delete("/api/brands/{brand_id}")
def delete_brand(brand_id: str, delete_data: bool = False):
    brand = config_manager.get_brand(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found.")

    docker_manager.stop_container(brand["container_name"])
    docker_manager.remove_container(brand["container_name"])

    success = config_manager.delete_brand(brand_id, delete_data=delete_data)
    if brand_id in brand_states:
        del brand_states[brand_id]
    return JSONResponse({"success": success})


REDROID_PS1_SCRIPT = Path(__file__).resolve().parent.parent / "ytuploader" / "redroid.ps1"


async def _run_streaming_command(brand_id: str, cmd: list) -> int:
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
            for line in iter(proc.stdout.readline, ''):
                asyncio.run_coroutine_threadsafe(
                    process_manager.broadcast_log(brand_id, line),
                    loop
                )
            proc.stdout.close()
            return proc.wait()
        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                process_manager.broadcast_log(brand_id, f"[ERROR] Execution failed ({type(e).__name__}): {e}\n"),
                loop
            )
            return 1

    loop = asyncio.get_running_loop()
    return await asyncio.to_thread(_worker)


async def _background_start_brand(brand: Dict[str, Any]):
    brand_id = brand["brand_id"]
    container_name = brand["container_name"]
    host_port = brand["host_port"]
    brand_states[brand_id] = "BOOTING"

    await process_manager.broadcast_log(brand_id, f"======================================================\n")
    await process_manager.broadcast_log(brand_id, f"  STARTING REDROID INSTANCE: {brand['name']} ({container_name})\n")
    await process_manager.broadcast_log(brand_id, f"======================================================\n")

    if os.name == "nt" and REDROID_PS1_SCRIPT.exists():
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", str(REDROID_PS1_SCRIPT),
            "start", container_name
        ]
        await process_manager.broadcast_log(brand_id, f"[*] Executing .\\ytuploader\\redroid.ps1 start {container_name}...\n")
        exit_code = await _run_streaming_command(brand_id, cmd)
        if exit_code != 0:
            await process_manager.broadcast_log(brand_id, f"[!] redroid.ps1 returned code {exit_code}. Verifying ADB boot state...\n")
    else:
        success, msg = docker_manager.start_container(brand, config_manager.get_settings())
        await process_manager.broadcast_log(brand_id, f"[*] {msg}\n")

    # Verify boot completion with ADB
    await process_manager.broadcast_log(brand_id, f"[*] Verifying Android boot completion on 127.0.0.1:{host_port}...\n")
    is_ready = await adb_manager.wait_for_boot(host_port, timeout_sec=60)
    if is_ready:
        brand_states[brand_id] = "READY"
        await process_manager.broadcast_log(brand_id, f"[+] SUCCESS: Android is online and READY on 127.0.0.1:{host_port}!\n")
    else:
        c_status = docker_manager.get_container_status(container_name)
        if c_status == "running":
            brand_states[brand_id] = "READY" if adb_manager.is_boot_completed(host_port) else "BOOTING"
            await process_manager.broadcast_log(brand_id, f"[*] Container is running. Status: {brand_states[brand_id]}\n")
        else:
            brand_states[brand_id] = "ERROR"
            await process_manager.broadcast_log(brand_id, f"[ERROR] Android boot timed out or container exited.\n")


async def _background_stop_brand(brand: Dict[str, Any]):
    brand_id = brand["brand_id"]
    container_name = brand["container_name"]
    host_port = brand["host_port"]
    brand_states[brand_id] = "STOPPED"

    await process_manager.broadcast_log(brand_id, f"[*] Stopping container {container_name}...\n")
    if os.name == "nt" and REDROID_PS1_SCRIPT.exists():
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", str(REDROID_PS1_SCRIPT),
            "stop", container_name
        ]
        await _run_streaming_command(brand_id, cmd)
    else:
        docker_manager.stop_container(container_name)

    adb_manager.disconnect(host_port)
    await process_manager.broadcast_log(brand_id, f"[+] Container {container_name} STOPPED.\n")


@app.post("/api/brands/{brand_id}/start")
async def start_brand(brand_id: str, background_tasks: BackgroundTasks):
    brand = config_manager.get_brand(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found.")

    c_status = docker_manager.get_container_status(brand["container_name"])
    if c_status == "running" and adb_manager.is_boot_completed(brand["host_port"]):
        brand_states[brand_id] = "READY"
        return JSONResponse({"success": True, "message": f"{brand['name']} is already running.", "state": "READY"})

    brand_states[brand_id] = "BOOTING"
    background_tasks.add_task(_background_start_brand, brand)
    return JSONResponse({"success": True, "message": f"Starting {brand['name']} via redroid.ps1...", "state": "BOOTING"})


@app.post("/api/brands/{brand_id}/stop")
async def stop_brand(brand_id: str, background_tasks: BackgroundTasks):
    brand = config_manager.get_brand(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found.")

    brand_states[brand_id] = "STOPPED"
    background_tasks.add_task(_background_stop_brand, brand)
    return JSONResponse({"success": True, "message": f"Stopping {brand['name']}...", "state": "STOPPED"})


@app.post("/api/brands/{brand_id}/scrcpy")
@app.post("/api/brands/{brand_id}/login")
async def launch_login_scrcpy(brand_id: str, background_tasks: BackgroundTasks):
    brand = config_manager.get_brand(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found.")

    c_state = docker_manager.get_container_status(brand["container_name"])
    if c_state != "running":
        brand_states[brand_id] = "BOOTING"
        background_tasks.add_task(_background_start_brand, brand)
        return JSONResponse({"success": False, "booting": True, "message": "Container is starting up. Screen will open once ready."})

    adb_manager.connect(brand["host_port"])
    success, msg = process_manager.launch_scrcpy(brand)
    if not success:
        raise HTTPException(status_code=500, detail=msg)
    return JSONResponse({"success": True, "message": msg})


@app.get("/api/brands/{brand_id}/container-logs")
def get_brand_container_logs(brand_id: str, log_type: Optional[str] = "all"):
    brand = config_manager.get_brand(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found.")

    c_name = brand["container_name"]
    host_port = brand["host_port"]
    target = f"127.0.0.1:{host_port}"
    adb_manager.connect(host_port)

    # 1. Morphe YouTube & Audio Logs (Filtered from Logcat)
    import re
    pids_out = adb_manager.run_adb(target, "shell", "pidof", "app.morphe.android.youtube", "app.revanced.android.gms", "audioserver", timeout=2).stdout
    pids = set(pids_out.strip().split()) if pids_out else set()

    raw_logcat = adb_manager.run_adb(target, "logcat", "-v", "time", "-d", "-t", "400", timeout=3).stdout
    if (not raw_logcat or not raw_logcat.strip()) and host_port == 5555:
        raw_logcat = adb_manager.run_adb("emulator-5554", "logcat", "-v", "time", "-d", "-t", "400", timeout=3).stdout

    morphe_keywords = [
        "app.morphe.android.youtube", "app.revanced.android.gms", "AndroidRuntime",
        "FATAL", "ExoPlayer", "AudioTrack", "audioserver", "audio_hw",
        "MediaCodec", "Shorts", "CreateShortEngine", "morphe"
    ]
    pattern = re.compile("|".join(morphe_keywords), re.IGNORECASE)

    morphe_lines = []
    if raw_logcat:
        for line in raw_logcat.splitlines():
            if pattern.search(line) or (pids and any(f"({p}):" in line or f" {p} " in line for p in pids)):
                morphe_lines.append(line)

    if morphe_lines:
        morphe_output = "\n".join(morphe_lines[-200:])
    else:
        morphe_output = "[No active Morphe logs captured or app is currently idle]"

    # 2. Container Console Logs (Docker)
    c_status = docker_manager.get_container_status(c_name)
    if c_status == "running":
        docker_output = docker_manager.get_container_logs(c_name, tail=150)
    else:
        docker_output = f"[Container '{c_name}' is currently {c_status.upper()}]"

    # 3. Start File / Boot Script Logs
    boot_list = process_manager.get_boot_logs(brand_id)
    if not boot_list:
        boot_list = process_manager.get_recent_logs(brand_id)
    start_output = "".join(boot_list[-100:]) if boot_list else "[No startup/boot execution logs recorded yet]"

    # 4. All Combined
    combined = (
        f"=== [1] MORPHE YOUTUBE & AUDIO LOGS ({target}) ===\n{morphe_output}\n\n"
        f"=== [2] DOCKER CONTAINER CONSOLE LOGS ({c_name}) ===\n{docker_output}\n\n"
        f"=== [3] START FILE & BOOT LOGS ===\n{start_output}\n"
    )

    if log_type == "morphe":
        selected = morphe_output
    elif log_type == "container":
        selected = docker_output
    elif log_type == "start":
        selected = start_output
    else:
        selected = combined

    return JSONResponse({
        "brand_id": brand_id,
        "name": brand["name"],
        "log_type": log_type,
        "morphe_logs": morphe_output,
        "container_logs": docker_output,
        "start_logs": start_output,
        "all_logs": combined,
        "logs": selected
    })


UPLOADS_DIR = BASE_DIR / "data" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/api/upload-media")
async def upload_media_file(file: UploadFile = File(...)):
    filename = file.filename
    dest_path = UPLOADS_DIR / filename
    with open(dest_path, "wb") as buffer:
        while chunk := await file.read(1024 * 1024):
            buffer.write(chunk)
    return JSONResponse({"success": True, "file_path": str(dest_path.resolve()), "filename": filename})


@app.post("/api/brands/{brand_id}/upload")
async def trigger_upload(brand_id: str, req: UploadRequest, background_tasks: BackgroundTasks):
    brand = config_manager.get_brand(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found.")

    c_state = docker_manager.get_container_status(brand["container_name"])
    if c_state != "running":
        # Auto-start container in background
        background_tasks.add_task(_background_start_brand, brand)

    background_tasks.add_task(
        process_manager.run_upload_task,
        brand=brand,
        video_path=req.video_path,
        title=req.title,
        sound=req.sound,
        timestamp=req.timestamp
    )

    return JSONResponse({
        "success": True,
        "message": f"Upload job initiated for '{brand['name']}'.",
        "brand_id": brand_id
    })


@app.post("/api/brands/{brand_id}/stop-upload")
async def stop_brand_upload(brand_id: str):
    brand = config_manager.get_brand(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found.")

    success, msg = process_manager.stop_upload_task(brand_id)
    return JSONResponse({"success": success, "message": msg})


@app.post("/api/brands/{brand_id}/pause-upload")
async def toggle_brand_upload_pause(brand_id: str):
    brand = config_manager.get_brand(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found.")

    success, is_paused, msg = process_manager.toggle_pause_upload(brand_id)
    return JSONResponse({"success": success, "is_paused": is_paused, "message": msg})


@app.websocket("/ws/logs/{brand_id}")
async def websocket_logs(websocket: WebSocket, brand_id: str):
    await websocket.accept()
    queue = process_manager.get_log_queue(brand_id)

    # Send recent system / boot stream lines
    recent_logs = process_manager.get_recent_logs(brand_id)
    for past_line in recent_logs:
        await websocket.send_text(past_line)

    active_job = process_manager.active_uploads.get(brand_id)
    if active_job and active_job.get("logs"):
        for past_line in active_job["logs"]:
            await websocket.send_text(past_line)

    try:
        while True:
            line = await queue.get()
            await websocket.send_text(line)
    except WebSocketDisconnect:
        process_manager.unsubscribe_log_queue(brand_id, queue)
    except Exception:
        process_manager.unsubscribe_log_queue(brand_id, queue)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
