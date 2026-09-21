import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from whisper_transcriber import FasterWhisperTranscriber


class WhisperTranscriberTests(unittest.TestCase):
    def test_configuration_defaults_to_cpu_int8(self):
        transcriber = FasterWhisperTranscriber({"model": "small"})
        self.assertEqual(transcriber.model_name, "small")
        self.assertEqual(transcriber.device, "cpu")
        self.assertEqual(transcriber.compute_type, "int8")

    def test_transcription_joins_segments_and_removes_temporary_audio(self):
        transcriber = FasterWhisperTranscriber()
        fake_model = SimpleNamespace(
            transcribe=lambda *_args, **_kwargs: (
                iter([SimpleNamespace(text=" こんにちは"), SimpleNamespace(text="案内して！ ")]),
                None,
            )
        )
        seen_path = ""
        original = tempfile.NamedTemporaryFile

        def remember_path(*args, **kwargs):
            nonlocal seen_path
            handle = original(*args, **kwargs)
            seen_path = handle.name
            return handle

        with patch.object(transcriber, "status", return_value=SimpleNamespace(ready=True, reason="")), \
             patch.object(transcriber, "_load_model", return_value=fake_model), \
             patch("whisper_transcriber.tempfile.NamedTemporaryFile", side_effect=remember_path):
            result = transcriber.transcribe(b"audio", "audio/webm;codecs=opus")

        self.assertEqual(result, "こんにちは案内して！")
        self.assertFalse(Path(seen_path).exists())

    def test_festival_hotwords_and_noise_vad_are_passed_to_whisper(self):
        seen_kwargs = {}

        def transcribe(*_args, **kwargs):
            seen_kwargs.update(kwargs)
            return iter([SimpleNamespace(text=" 物理部はどこ？")]), None

        transcriber = FasterWhisperTranscriber({
            "hotwords": ["海城祭", "物理部"],
            "initial_prompt": "海城祭の案内会話です。",
            "vad_threshold": 0.3,
            "min_speech_duration_ms": 100,
            "min_silence_duration_ms": 250,
            "speech_pad_ms": 180,
        })
        fake_model = SimpleNamespace(transcribe=transcribe)
        with patch.object(transcriber, "status", return_value=SimpleNamespace(ready=True, reason="")), \
             patch.object(transcriber, "_load_model", return_value=fake_model):
            result = transcriber.transcribe(b"audio", "audio/webm")

        self.assertEqual(result, "物理部はどこ？")
        self.assertEqual(seen_kwargs["hotwords"], "海城祭 物理部")
        self.assertEqual(seen_kwargs["initial_prompt"], "海城祭の案内会話です。")
        self.assertEqual(seen_kwargs["vad_parameters"]["threshold"], 0.3)
        self.assertEqual(seen_kwargs["vad_parameters"]["speech_pad_ms"], 180)


if __name__ == "__main__":
    unittest.main()
