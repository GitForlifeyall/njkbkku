import json
import os
import re
import socket
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "brands.json"
DATA_ROOT = Path(__file__).resolve().parent.parent / "data"

_lock = threading.Lock()


def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
    """Verifies host port is not already bound before assigning or launching container."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


class ConfigManager:
    def __init__(self, config_path: Path = CONFIG_FILE):
        self.config_path = config_path
        self._ensure_config_file()

    def _ensure_config_file(self):
        if not self.config_path.parent.exists():
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            default_data = {
                "settings": {
                    "base_image": "redroid/redroid:13.0.0_64only-latest",
                    "base_port": 5555,
                    "memory_limit": "1800m",
                    "default_resolution": "720x1280",
                    "default_fps": 30,
                    "default_dpi": 320
                },
                "brands": []
            }
            self._save_raw(default_data)

    def _load_raw(self) -> Dict[str, Any]:
        with _lock:
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {"settings": {}, "brands": []}

    def _save_raw(self, data: Dict[str, Any]):
        with _lock:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

    def get_settings(self) -> Dict[str, Any]:
        return self._load_raw().get("settings", {})

    def get_all_brands(self) -> List[Dict[str, Any]]:
        return self._load_raw().get("brands", [])

    def get_brand(self, brand_id: str) -> Optional[Dict[str, Any]]:
        brands = self.get_all_brands()
        for b in brands:
            if b.get("brand_id") == brand_id:
                return b
        return None

    def get_next_available_port(self) -> int:
        data = self._load_raw()
        base_port = data.get("settings", {}).get("base_port", 5555)
        assigned_ports = {b.get("host_port") for b in data.get("brands", []) if b.get("host_port")}
        
        candidate = base_port
        while True:
            if candidate not in assigned_ports and is_port_available(candidate):
                return candidate
            candidate += 1

    def add_brand(self, name: str, brand_id: Optional[str] = None) -> Dict[str, Any]:
        data = self._load_raw()
        brands = data.get("brands", [])
        
        if not brand_id:
            safe_slug = re.sub(r'[^a-zA-Z0-9_]', '_', name.lower().strip())
            safe_slug = re.sub(r'_+', '_', safe_slug).strip('_')
            brand_id = safe_slug or f"brand_{len(brands) + 1:02d}"
        
        existing_ids = {b.get("brand_id") for b in brands}
        unique_id = brand_id
        counter = 1
        while unique_id in existing_ids:
            unique_id = f"{brand_id}_{counter}"
            counter += 1

        allocated_port = self.get_next_available_port()
        container_name = f"redroid-{unique_id.replace('_', '-')}"
        data_dir_rel = f"./data/{unique_id}"
        data_dir_abs = DATA_ROOT / unique_id
        data_dir_abs.mkdir(parents=True, exist_ok=True)

        new_brand = {
            "brand_id": unique_id,
            "name": name.strip(),
            "container_name": container_name,
            "host_port": allocated_port,
            "data_dir": data_dir_rel,
            "created_at": None
        }

        brands.append(new_brand)
        data["brands"] = brands
        self._save_raw(data)
        return new_brand

    def delete_brand(self, brand_id: str, delete_data: bool = False) -> bool:
        data = self._load_raw()
        brands = data.get("brands", [])
        brand_to_delete = None
        new_brands = []
        for b in brands:
            if b.get("brand_id") == brand_id:
                brand_to_delete = b
            else:
                new_brands.append(b)

        if not brand_to_delete:
            return False

        data["brands"] = new_brands
        self._save_raw(data)

        if delete_data:
            data_dir_abs = DATA_ROOT / brand_id
            if data_dir_abs.exists():
                import shutil
                try:
                    shutil.rmtree(data_dir_abs)
                except Exception:
                    pass
        return True


config_manager = ConfigManager()
