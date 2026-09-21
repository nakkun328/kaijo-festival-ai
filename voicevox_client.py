from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class VoicevoxStatus:
    ready: bool
    version: str = ""
    reason: str = ""


class VoicevoxError(RuntimeError):
    pass


class VoicevoxClient:
    def __init__(self, config: dict[str, Any]):
        self.engine_type = str(config.get("engine", "voicevox")).strip().lower()
        labels = {"aivisspeech": "AivisSpeech", "coeiroink": "COEIROINK"}
        self.engine_label = labels.get(self.engine_type, "VOICEVOX")
        self.base_url = str(config.get("base_url", "http://127.0.0.1:50021")).rstrip("/")
        self.speaker_id = int(config.get("speaker_id", 13))
        self.speaker_uuid = str(config.get("speaker_uuid", "")).strip()
        self.style_id = int(config.get("style_id", self.speaker_id))
        self.speaker_label = str(config.get("speaker_label", "")).strip()
        self.speed_scale = float(config.get("speed_scale", 1.08))
        self.intonation_scale = float(config.get("intonation_scale", 1.08))
        self.pitch_scale = float(config.get("pitch_scale", 0.0))
        self.pause_length_scale = float(config.get("pause_length_scale", 1.0))
        self.tempo_dynamics_scale = float(config.get("tempo_dynamics_scale", 1.0))
        self._synthesis_lock = threading.Lock()

    def status(self) -> VoicevoxStatus:
        if self.engine_type == "coeiroink":
            try:
                with urllib.request.urlopen(f"{self.base_url}/openapi.json", timeout=3) as response:
                    json.loads(response.read().decode("utf-8"))
                detail = self.speaker_label or f"style {self.style_id}"
                return VoicevoxStatus(True, detail)
            except Exception:
                return VoicevoxStatus(False, reason="COEIROINKが起動していません。ブラウザ音声で再生します。")
        try:
            with urllib.request.urlopen(f"{self.base_url}/version", timeout=2) as response:
                version = json.loads(response.read().decode("utf-8"))
            return VoicevoxStatus(True, str(version))
        except Exception:
            return VoicevoxStatus(False, reason=f"{self.engine_label} Engineが起動していません。ブラウザ音声で再生します。")

    def synthesize(self, text: str, *, emotion: str = "neutral", intensity: object = 0.65) -> bytes:
        text = text.strip()
        if not text:
            raise VoicevoxError("読み上げる文章がありません。")
        if len(text) > 2_000:
            raise VoicevoxError("読み上げる文章が長すぎます。")
        if self.engine_type == "coeiroink":
            with self._synthesis_lock:
                return self._synthesize_coeiroink(text, emotion=emotion, intensity=intensity)
        params = urllib.parse.urlencode({"text": text, "speaker": self.speaker_id})
        query = self._post_json(f"{self.base_url}/audio_query?{params}", None)
        profiles = {
            "neutral": (1.00, 1.00, 0.00),
            "happy": (1.025, 1.055, 0.008),
            "excited": (1.055, 1.09, 0.015),
            "thinking": (0.975, 0.97, -0.006),
            "surprised": (1.04, 1.075, 0.012),
            "concerned": (0.965, 0.94, -0.01),
        }
        target_speed, target_intonation, target_pitch = profiles.get(emotion, profiles["neutral"])
        try:
            blend = max(0.3, min(1.0, float(intensity)))
        except (TypeError, ValueError):
            blend = 0.65
        query["speedScale"] = self.speed_scale + (target_speed - 1.0) * blend
        query["intonationScale"] = self.intonation_scale + (target_intonation - 1.0) * blend
        if self.engine_type == "aivisspeech":
            # AivisSpeech uses the original text and tempo dynamics to preserve
            # Style-Bert-VITS2's contextual rhythm. Pitch shifting degrades quality.
            query["kana"] = text
            query["pitchScale"] = 0.0
            query["tempoDynamicsScale"] = self.tempo_dynamics_scale + (target_speed - 1.0) * blend
        else:
            query["pitchScale"] = self.pitch_scale + target_pitch * blend
            query["pauseLengthScale"] = self.pause_length_scale
        query["prePhonemeLength"] = max(0.08, float(query.get("prePhonemeLength", 0.1)))
        query["postPhonemeLength"] = max(0.12, float(query.get("postPhonemeLength", 0.1)))
        try:
            response = httpx.post(
                f"{self.base_url}/synthesis",
                params={"speaker": self.speaker_id},
                json=query,
                headers={"Accept": "audio/wav"},
                timeout=60,
            )
            response.raise_for_status()
            return response.content
        except Exception as exc:
            raise VoicevoxError(f"{self.engine_label}の音声生成に失敗しました: {exc}") from exc

    def _synthesize_coeiroink(self, text: str, *, emotion: str, intensity: object) -> bytes:
        # The legacy COEIROINK processing algorithm expects unmodified scales
        # when prosodyDetail/adjustedF0 are empty. Emotion-based scale changes
        # make the engine return HTTP 500, so keep the configured native voice.
        payload = {
            "volumeScale": 1.0,
            "pitchScale": self.pitch_scale,
            "intonationScale": self.intonation_scale,
            "prePhonemeLength": 0.08,
            "postPhonemeLength": 0.15,
            "outputSamplingRate": 44_100,
            "sampledIntervalValue": 0,
            "adjustedF0": [],
            "processingAlgorithm": "coeiroink",
            "speakerUuid": self.speaker_uuid,
            "styleId": self.style_id,
            "text": text,
            "prosodyDetail": [],
            "speedScale": self.speed_scale,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/v1/synthesis",
                json=payload,
                headers={"Accept": "audio/wav"},
                timeout=90,
            )
            response.raise_for_status()
            return response.content
        except Exception as exc:
            raise VoicevoxError(f"COEIROINKの音声生成に失敗しました: {exc}") from exc

    @staticmethod
    def _post_json(url: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8") if payload is not None else b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise VoicevoxError(f"音声合成エンジンへ接続できません: {exc}") from exc
