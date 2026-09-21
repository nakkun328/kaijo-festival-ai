from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(slots=True)
class OperationTimer:
    duration_ms: float = 0.0


class Telemetry:
    """Thread-safe, process-local health and latency measurements for exhibition mode."""

    def __init__(self, history_size: int = 100):
        self.started_at = time.time()
        self._history_size = history_size
        self._timings: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=history_size))
        self._counts: dict[str, int] = defaultdict(int)
        self._errors: dict[str, int] = defaultdict(int)
        self._active: dict[str, int] = defaultdict(int)
        self._request_count = 0
        self._lock = threading.Lock()
        self._process: Any | None = None
        try:
            import psutil

            self._process = psutil.Process(os.getpid())
            psutil.cpu_percent(interval=None)
            self._process.cpu_percent(interval=None)
        except (ImportError, OSError):
            pass

    def hit(self) -> None:
        with self._lock:
            self._request_count += 1

    @contextmanager
    def measure(self, operation: str) -> Iterator[OperationTimer]:
        timer = OperationTimer()
        started = time.perf_counter()
        succeeded = False
        with self._lock:
            self._active[operation] += 1
        try:
            yield timer
            succeeded = True
        finally:
            timer.duration_ms = round((time.perf_counter() - started) * 1000, 1)
            with self._lock:
                self._active[operation] = max(0, self._active[operation] - 1)
                self._timings[operation].append(timer.duration_ms)
                self._counts[operation] += 1
                if not succeeded:
                    self._errors[operation] += 1

    def reset(self) -> None:
        with self._lock:
            self._timings.clear()
            self._counts.clear()
            self._errors.clear()
            self._request_count = 0

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            operation_names = sorted(set(self._timings) | set(self._errors) | set(self._active))
            operations = {}
            for name in operation_names:
                values = list(self._timings[name])
                operations[name] = {
                    "count": self._counts[name],
                    "errors": self._errors[name],
                    "active": self._active[name],
                    "latestMs": values[-1] if values else None,
                    "averageMs": round(sum(values) / len(values), 1) if values else None,
                    "maxMs": max(values) if values else None,
                }
            request_count = self._request_count

        load: dict[str, float | None] = {
            "cpuPercent": None,
            "memoryPercent": None,
            "memoryUsedGb": None,
            "memoryTotalGb": None,
            "processCpuPercent": None,
            "processMemoryMb": None,
            "diskPercent": None,
        }
        try:
            import psutil

            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(os.path.abspath(os.sep))
            process = self._process or psutil.Process(os.getpid())
            load.update(
                cpuPercent=round(psutil.cpu_percent(interval=None), 1),
                memoryPercent=round(memory.percent, 1),
                memoryUsedGb=round(memory.used / (1024**3), 1),
                memoryTotalGb=round(memory.total / (1024**3), 1),
                processCpuPercent=round(process.cpu_percent(interval=None), 1),
                processMemoryMb=round(process.memory_info().rss / (1024**2), 1),
                diskPercent=round(disk.percent, 1),
            )
        except (ImportError, OSError):
            pass

        return {
            "uptimeSeconds": max(0, int(time.time() - self.started_at)),
            "requestCount": request_count,
            "load": load,
            "operations": operations,
            "gpus": self._gpu_snapshot(),
        }

    @staticmethod
    def _gpu_snapshot() -> list[dict[str, Any]]:
        executable = shutil.which("nvidia-smi")
        if not executable:
            windows_path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "nvidia-smi.exe")
            executable = windows_path if os.path.isfile(windows_path) else None
        if not executable:
            return []

        startup_info = None
        if os.name == "nt":
            startup_info = subprocess.STARTUPINFO()
            startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            result = subprocess.run(
                [
                    executable,
                    "--query-gpu=index,name,utilization.gpu,temperature.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                check=True,
                startupinfo=startup_info,
            )
        except (OSError, subprocess.SubprocessError):
            return []

        gpus: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) != 6:
                continue
            try:
                index, name = int(parts[0]), parts[1]
                utilization, temperature = float(parts[2]), float(parts[3])
                memory_used, memory_total = float(parts[4]), float(parts[5])
            except ValueError:
                continue
            gpus.append(
                {
                    "index": index,
                    "name": name,
                    "utilizationPercent": utilization,
                    "temperatureC": temperature,
                    "memoryUsedMb": memory_used,
                    "memoryTotalMb": memory_total,
                    "memoryPercent": round(memory_used / memory_total * 100, 1) if memory_total else 0.0,
                }
            )
        return gpus
