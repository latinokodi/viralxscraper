"""Internet Download Manager queue helper."""
import os
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_IDM_PATHS = [
    Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "Internet Download Manager" / "IDMan.exe",
    Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Internet Download Manager" / "IDMan.exe",
    Path("C:\\Program Files (x86)\\Internet Download Manager\\IDMan.exe"),
    Path("C:\\Program Files\\Internet Download Manager\\IDMan.exe"),
]

def find_idm() -> Optional[Path]:
    for p in _IDM_PATHS:
        if p.exists():
            return p
    return None


def queue_in_idm(urls: list[str], folder: str, filenames: Optional[list[str]] = None) -> int:
    """
    Queue URLs in Internet Download Manager.
    
    Args:
        urls: List of download URLs
        folder: Destination folder path
        filenames: Optional list of filenames (same length as urls)
    
    Returns:
        Number of items successfully queued
    """
    idm = find_idm()
    if not idm:
        raise RuntimeError("IDMan.exe not found. Install Internet Download Manager.")
    
    folder = os.path.abspath(folder)
    os.makedirs(folder, exist_ok=True)
    
    if filenames is None:
        filenames = [None] * len(urls)
    
    success = 0
    for i, url in enumerate(urls):
        fname = filenames[i] if i < len(filenames) else None
        cmd = [str(idm), "/d", url, "/a"]
        if fname:
            cmd.extend(["/f", str(fname)])
        cmd.extend(["/p", folder])
        try:
            subprocess.run(cmd, creationflags=0x08000000, check=True)
            success += 1
        except Exception as e:
            log.warning("IDM queue failed for %s: %s", url[:80], e)
    
    return success


# ── Persistent config ────────────────────────────────────────────────

_CONFIG_DIR = Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "viralxscraper"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

def load_config() -> dict:
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}

def save_config(cfg: dict):
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

def get_download_folder() -> str:
    """Get the saved download folder, or default to ~/Downloads/viralxscraper."""
    cfg = load_config()
    folder = cfg.get("download_folder", "")
    if folder and os.path.isdir(folder):
        return folder
    # Default
    default = str(Path.home() / "Downloads" / "viralxscraper")
    os.makedirs(default, exist_ok=True)
    return default

def set_download_folder(folder: str):
    cfg = load_config()
    cfg["download_folder"] = os.path.abspath(folder)
    save_config(cfg)
