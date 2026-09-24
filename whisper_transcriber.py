from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


class TranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TranscriberStatus:
    ready: bool
    model: str
    device: str
    compute_type: str
    reason: str = ""


class FasterWhisperTranscriber:
    """Lazy, process-local faster-whisper transcription with ephemeral audio files."""

    EXTENSIONS = {
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
    }

    def __init__(self, config: dict[str, Any] | None = None):
        settings = config or {}
        self.model_name = os.getenv("WHISPER_MODEL", str(settings.get("model", "small")))
        self.device = os.getenv("WHISPER_DEVICE", str(settings.get("device", "cpu")))
        default_compute = "int8" if self.device == "cpu" else "float16"
        self.compute_type = os.getenv(
            "WHISPER_COMPUTE_TYPE", str(settings.get("compute_type", default_compute))
        )
        configured_root = os.getenv(
            "WHISPER_MODEL_DIR", str(settings.get("model_dir", ROOT / "data" / "whisper-models"))
        )
        self.model_dir = Path(configured_root).expanduser().resolve()
        self.language = str(settings.get("language", "ja"))
        configured_hotwords = settings.get("hotwords", "")
        if isinstance(configured_hotwords, list):
            configured_hotwords = " ".join(str(item).strip() for item in configured_hotwords if str(item).strip())
        self.hotwords = str(configured_hotwords).strip() or None
        self.initial_prompt = str(settings.get("initial_prompt", "")).strip() or None
        self.vad_parameters = {
            "threshold": float(settings.get("vad_threshold", 0.35)),
            "min_speech_duration_ms": int(settings.get("min_speech_duration_ms", 120)),
            "min_silence_duration_ms": int(settings.get("min_silence_duration_ms", 300)),
            "speech_pad_ms": int(settings.get("speech_pad_ms", 160)),
        }
        self._model: Any | None = None
        self._lock = threading.Lock()
        self._cuda_dll_handle: Any | None = None

    def status(self) -> TranscriberStatus:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return TranscriberStatus(
                False,
                self.model_name,
                self.device,
                self.compute_type,
                "faster-whisperが未インストールです。pip install -r requirements.txt を実行してください。",
            )
        return TranscriberStatus(True, self.model_name, self.device, self.compute_type)

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        if self.device == 'cuda' and os.name == 'nt' and self._cuda_dll_handle is None:
            local_app_data = os.environ.get('LOCALAPPDATA')
            if local_app_data:
                ollama_cuda = Path(local_app_data) / 'Programs' / 'Ollama' / 'lib' / 'ollama' / 'cuda_v12'
                if ollama_cuda.is_dir():
                    os.environ['PATH'] = str(ollama_cuda) + os.pathsep + os.environ.get('PATH', '')
                    self._cuda_dll_handle = os.add_dll_directory(str(ollama_cuda))
        try:
            import truststore

            truststore.inject_into_ssl()
        except ImportError:
            pass
        from faster_whisper import WhisperModel

        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
            download_root=str(self.model_dir),
        )
        return self._model

    def _recognize(self, model: Any, temporary_path: str) -> str:
        segments, _ = model.transcribe(
            temporary_path,
            language=self.language,
            beam_size=1,
            vad_filter=True,
            vad_parameters=self.vad_parameters,
            condition_on_previous_text=False,
            without_timestamps=True,
            initial_prompt=self.initial_prompt,
            hotwords=self.hotwords,
        )
        return "".join(segment.text for segment in segments).strip()

    def transcribe(self, audio: bytes, content_type: str = "audio/webm") -> str:
        if not audio:
            raise ValueError("録音データが空です。")
        status = self.status()
        if not status.ready:
            raise TranscriptionError(status.reason)

        media_type = content_type.split(";", 1)[0].strip().lower()
        suffix = self.EXTENSIONS.get(media_type, ".webm")
        temporary_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temporary:
                temporary.write(audio)
                temporary_path = temporary.name
            with self._lock:
                try:
                    text = self._recognize(self._load_model(), temporary_path)
                except RuntimeError as exc:
                    gpu_error = any(marker in str(exc).lower() for marker in
                                    ('cuda', 'cublas', 'cudnn', 'out of memory', 'driver'))
                    if self.device != 'cuda' or not gpu_error:
                        raise
                    self._model = None
                    self.device = 'cpu'
                    self.compute_type = 'int8'
                    text = self._recognize(self._load_model(), temporary_path)
            if not text:
                raise ValueError("声を認識できませんでした。もう一度、少し大きめの声で話してください。")
            return text
        except (ValueError, TranscriptionError):
            raise
        except Exception as exc:
            raise TranscriptionError(f"音声認識に失敗しました: {exc}") from exc
        finally:
            if temporary_path:
                Path(temporary_path).unlink(missing_ok=True)
