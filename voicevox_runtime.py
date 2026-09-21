from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_ENGINE = ROOT / "tools" / "voicevox-engine" / "windows-cpu" / "run.exe"
DEFAULT_AIVIS_ENGINE = ROOT / "tools" / "aivisspeech-engine" / "Windows-x64" / "run.exe"
DEFAULT_COEIROINK_ENGINE = (
    ROOT / "tools" / "coeiroink" / "engine" / "COEIROINK_WIN_CPU_v.2.13.0" / "engine" / "engine.exe"
)


def _engine_ready(base_url: str, engine_type: str = "voicevox") -> bool:
    try:
        endpoint = "/openapi.json" if engine_type == "coeiroink" else "/version"
        with urllib.request.urlopen(f"{base_url.rstrip('/')}{endpoint}", timeout=1) as response:
            json.loads(response.read().decode("utf-8"))
        return True
    except Exception:
        return False


def ensure_voicevox_engine(config: dict[str, Any], timeout_seconds: float = 30.0) -> bool:
    """Start the configured local VOICEVOX-compatible engine when needed."""
    engine_type = str(config.get("engine", "voicevox")).strip().lower()
    base_url = str(config.get("base_url", "http://127.0.0.1:50021")).rstrip("/")
    if _engine_ready(base_url, engine_type):
        return True
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        return False

    default_engines = {
        "aivisspeech": DEFAULT_AIVIS_ENGINE,
        "coeiroink": DEFAULT_COEIROINK_ENGINE,
    }
    default_engine = default_engines.get(engine_type, DEFAULT_ENGINE)
    configured_path = Path(str(config.get("engine_path", default_engine)))
    engine_path = (configured_path if configured_path.is_absolute() else ROOT / configured_path).resolve()
    if not engine_path.is_file():
        return False

    if engine_type == "coeiroink":
        arguments = [str(engine_path)]
        working_directory = engine_path.parent.parent
    else:
        port = parsed.port or (10101 if engine_type == "aivisspeech" else 50021)
        arguments = [str(engine_path), "--host", "127.0.0.1", "--port", str(port)]
        working_directory = engine_path.parent
    if engine_type == "aivisspeech":
        arguments.extend(("--disable_mutable_api", "--output_log_utf8"))
    elif engine_type == "voicevox":
        arguments.extend(("--disable_mutable_api", "--output_log_utf8"))

    creation_flags = 0
    for flag_name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS"):
        creation_flags |= int(getattr(subprocess, flag_name, 0))
    subprocess.Popen(
        arguments,
        cwd=working_directory,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _engine_ready(base_url, engine_type):
            return True
        time.sleep(0.25)
    return False
