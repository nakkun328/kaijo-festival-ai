from __future__ import annotations

import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parent


class SmartTurnError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmartTurnStatus:
    ready: bool
    model: str
    reason: str = ""


class SmartTurnDetector:
    """Local Pipecat Smart Turn v3.2 ONNX endpoint detector."""

    REPO_ID = "pipecat-ai/smart-turn-v3"
    FILENAME = "smart-turn-v3.2-cpu.onnx"

    def __init__(self, config: dict[str, Any] | None = None):
        settings = config or {}
        configured_dir = Path(str(settings.get("model_dir", "data/smart-turn")))
        self.model_dir = (configured_dir if configured_dir.is_absolute() else ROOT / configured_dir).resolve()
        self.threshold = float(settings.get("threshold", 0.5))
        self._session: Any | None = None
        self._extractor: Any | None = None
        self._lock = threading.Lock()

    def status(self) -> SmartTurnStatus:
        try:
            import onnxruntime  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return SmartTurnStatus(False, "Pipecat Smart Turn v3.2", "Smart Turnの依存関係が未導入です。")
        return SmartTurnStatus(True, "Pipecat Smart Turn v3.2")

    def _model_path(self) -> Path:
        direct = self.model_dir / self.FILENAME
        if direct.is_file():
            return direct
        try:
            import truststore

            truststore.inject_into_ssl()
        except ImportError:
            pass
        from huggingface_hub import hf_hub_download

        self.model_dir.mkdir(parents=True, exist_ok=True)
        downloaded = hf_hub_download(
            repo_id=self.REPO_ID,
            filename=self.FILENAME,
            local_dir=str(self.model_dir),
        )
        return Path(downloaded)

    def _load(self) -> None:
        if self._session is not None:
            return
        import onnxruntime as ort
        from transformers import WhisperFeatureExtractor

        options = ort.SessionOptions()
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(str(self._model_path()), sess_options=options)
        self._extractor = WhisperFeatureExtractor(chunk_length=8)

    def predict(self, audio: bytes, content_type: str = "audio/webm") -> tuple[bool, float]:
        if not audio:
            raise ValueError("録音データが空です。")
        suffixes = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/wav": ".wav"}
        media_type = content_type.split(";", 1)[0].strip().lower()
        temporary_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffixes.get(media_type, ".webm")) as temporary:
                temporary.write(audio)
                temporary_path = temporary.name
            from faster_whisper.audio import decode_audio

            samples = decode_audio(temporary_path, sampling_rate=16000)
            samples = samples[-128_000:]
            if len(samples) < 128_000:
                samples = np.pad(samples, (128_000 - len(samples), 0))
            with self._lock:
                self._load()
                inputs = self._extractor(
                    samples,
                    sampling_rate=16000,
                    return_tensors="np",
                    padding="max_length",
                    max_length=128_000,
                    truncation=True,
                    do_normalize=True,
                )
                features = np.expand_dims(inputs.input_features.squeeze(0).astype(np.float32), axis=0)
                probability = float(self._session.run(None, {"input_features": features})[0][0].item())
            return probability > self.threshold, probability
        except (ValueError, SmartTurnError):
            raise
        except Exception as exc:
            raise SmartTurnError(f"Smart Turn判定に失敗しました: {exc}") from exc
        finally:
            if temporary_path:
                Path(temporary_path).unlink(missing_ok=True)
