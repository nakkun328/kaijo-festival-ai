from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import threading
import time
import unicodedata
from html import escape
from collections import defaultdict, deque
from datetime import datetime
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, quote, urlparse
from zoneinfo import ZoneInfo

from festival_knowledge import FestivalKnowledgeBase, records_to_json
from input_guard import inspect_input
from model_providers import ModelProvider, ProviderError, create_providers
from persona_chat_prototype import load_config
from persona_core import PersonaState, build_system_prompt
from smart_turn_detector import SmartTurnDetector, SmartTurnError
from telemetry import Telemetry
from voicevox_client import VoicevoxClient, VoicevoxError
from voicevox_runtime import ensure_voicevox_engine
from whisper_transcriber import FasterWhisperTranscriber, TranscriptionError


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
mimetypes.add_type("image/webp", ".webp")

EMOTIONS = {"neutral", "happy", "excited", "thinking", "surprised", "concerned"}
GESTURES = {"nod", "tilt", "wave", "point", "cheer"}
ANIMATION_PATTERN = re.compile(
    r"^\s*\[\[emotion:(?P<emotion>[a-z]+)\|gesture:(?P<gesture>[a-z]+)\|intensity:(?P<intensity>(?:0(?:\.\d+)?|1(?:\.0+)?))\]\]\s*",
    re.IGNORECASE,
)
JAPAN_TIMEZONE = ZoneInfo("Asia/Tokyo")
JAPANESE_WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")


def format_ai_current_time(now: datetime | None = None) -> str:
    """Format the authoritative current time for the model, without seconds."""
    current = now or datetime.now(JAPAN_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=JAPAN_TIMEZONE)
    current = current.astimezone(JAPAN_TIMEZONE)
    weekday = JAPANESE_WEEKDAYS[current.weekday()]
    return (
        f"{current.year}年{current.month}月{current.day}日（{weekday}曜日）"
        f"{current.strftime('%H:%M')}（日本時間 / Asia/Tokyo）"
    )


def _svg_lines(value: Any, *, max_units: int, max_lines: int) -> list[str]:
    """Wrap Japanese text by approximate rendered width for an SVG text block."""
    text = re.sub(r"\s+", " ", str(value or "").strip()) or "記載なし"
    lines: list[str] = []
    current = ""
    current_units = 0
    consumed = 0
    for index, character in enumerate(text):
        units = 2 if unicodedata.east_asian_width(character) in {"W", "F", "A"} else 1
        if current and current_units + units > max_units:
            lines.append(current)
            if len(lines) == max_lines:
                consumed = index
                break
            current = ""
            current_units = 0
        current += character
        current_units += units
        consumed = index + 1
    if current and len(lines) < max_lines:
        lines.append(current)
    if consumed < len(text) and lines:
        lines[-1] = lines[-1].rstrip("…") + "…"
    return lines or ["記載なし"]


def _guide_date_time(record: dict[str, Any]) -> str:
    date = str(record.get("date", "")).strip()
    day = str(record.get("day", "")).strip()
    start = str(record.get("start_time", "")).strip()
    end = str(record.get("end_time", "")).strip()
    date_label = date
    if day:
        date_label = f"{date_label} ({day})" if date_label else day
    time_label = f"{start}-{end}" if start and end else start or end
    return " / ".join(part for part in (date_label, time_label) if part) or "時間の記載なし"


def render_guide_card_svg(record: dict[str, Any], festival_name: str = "第135代 海城祭") -> bytes:
    """Render one minimal, self-contained visual card from a verified official fact."""
    title_lines = _svg_lines(record.get("event_name"), max_units=34, max_lines=2)
    location_lines = _svg_lines(record.get("location"), max_units=44, max_lines=1)
    organization = _svg_lines(record.get("organization"), max_units=54, max_lines=1)[0]
    category = _svg_lines(record.get("category"), max_units=24, max_lines=1)[0]
    when = _guide_date_time(record)
    page = str(record.get("page", "")).strip()
    website_source = record.get("source_type") == "official_website"
    source_heading = "OFFICIAL WEBSITE" if website_source else "PAMPHLET GUIDE"
    source_badge = "WEB" if website_source else f"p.{page or '?'}"

    title_tspans = "".join(
        f'<tspan x="44" dy="{0 if index == 0 else 38}">{escape(line)}</tspan>'
        for index, line in enumerate(title_lines)
    )
    location_tspans = "".join(
        f'<tspan x="178" dy="{0 if index == 0 else 31}">{escape(line)}</tspan>'
        for index, line in enumerate(location_lines)
    )
    organization_y = 145 if len(title_lines) == 2 else 116
    location_y = 178
    time_y = 220
    footer_y = 246
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="260" viewBox="0 0 800 260" role="img" aria-labelledby="title desc">
<title id="title">{escape(str(record.get("event_name", "海城祭案内")))}</title>
<desc id="desc">公式資料に基づく場所と日時をまとめた案内カード</desc>
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#071727"/><stop offset="1" stop-color="#123f52"/></linearGradient>
  <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#51e3ff"/><stop offset="1" stop-color="#ff9b54"/></linearGradient>
</defs>
<rect width="800" height="260" rx="24" fill="url(#bg)"/>
<rect x="2" y="2" width="796" height="256" rx="22" fill="none" stroke="#51e3ff" stroke-opacity=".42" stroke-width="3"/>
<rect x="0" y="0" width="12" height="260" rx="6" fill="url(#accent)"/>
<text x="44" y="34" fill="#51e3ff" font-family="Yu Gothic, Noto Sans JP, sans-serif" font-size="15" font-weight="700" letter-spacing="2">{source_heading}</text>
<rect x="670" y="15" width="86" height="36" rx="18" fill="#ff9b54"/>
<text x="713" y="40" fill="#071727" text-anchor="middle" font-family="Yu Gothic, Noto Sans JP, sans-serif" font-size="18" font-weight="800">{escape(source_badge)}</text>
<text x="44" y="76" fill="#ffffff" font-family="Yu Gothic, Noto Sans JP, sans-serif" font-size="32" font-weight="800">{title_tspans}</text>
<text x="44" y="{organization_y}" fill="#b9d6e1" font-family="Yu Gothic, Noto Sans JP, sans-serif" font-size="17">{escape(organization)}</text>
<rect x="44" y="{location_y - 25}" width="88" height="30" rx="15" fill="#51e3ff" fill-opacity=".14"/>
<text x="88" y="{location_y - 4}" fill="#51e3ff" text-anchor="middle" font-family="Yu Gothic, Noto Sans JP, sans-serif" font-size="14" font-weight="800">場所</text>
<text x="154" y="{location_y - 3}" fill="#ffffff" font-family="Yu Gothic, Noto Sans JP, sans-serif" font-size="21" font-weight="700">{location_tspans}</text>
<rect x="44" y="{time_y - 25}" width="88" height="30" rx="15" fill="#ff9b54" fill-opacity=".16"/>
<text x="88" y="{time_y - 4}" fill="#ffb37d" text-anchor="middle" font-family="Yu Gothic, Noto Sans JP, sans-serif" font-size="14" font-weight="800">日時</text>
<text x="154" y="{time_y - 3}" fill="#ffffff" font-family="Yu Gothic, Noto Sans JP, sans-serif" font-size="19" font-weight="700">{escape(when)}</text>
<text x="44" y="{footer_y}" fill="#8fb2c0" font-family="Yu Gothic, Noto Sans JP, sans-serif" font-size="13">{escape(festival_name)}</text>
<text x="756" y="{footer_y}" fill="#8fb2c0" text-anchor="end" font-family="Yu Gothic, Noto Sans JP, sans-serif" font-size="13">{escape(category)}</text>
</svg>'''
    return svg.encode("utf-8")


def parse_animation_directive(answer: str) -> tuple[str, dict[str, Any]]:
    """Remove the private avatar control line and return safe animation values."""
    match = ANIMATION_PATTERN.match(answer)
    if match:
        emotion = match.group("emotion").lower()
        gesture = match.group("gesture").lower()
        if emotion in EMOTIONS and gesture in GESTURES:
            return answer[match.end():].lstrip(), {
                "emotion": emotion,
                "gesture": gesture,
                "intensity": max(0.3, min(1.0, float(match.group("intensity")))),
            }

    text = answer.strip()
    if any(word in text for word in ("ごめん", "心配", "困った", "難しい", "残念")):
        emotion = "concerned"
    elif any(word in text for word in ("びっくり", "驚", "まさか", "本当に！？")):
        emotion = "surprised"
    elif text.count("！") + text.count("!") >= 2 or any(word in text for word in ("最高", "すごい", "面白そう")):
        emotion = "excited"
    elif any(word in text for word in ("考えて", "なるほど", "たとえば", "つまり")):
        emotion = "thinking"
    elif any(word in text for word in ("いいね", "うれしい", "楽しい", "よし", "ありがとう")):
        emotion = "happy"
    else:
        emotion = "neutral"
    gesture = {
        "neutral": "nod", "happy": "wave", "excited": "cheer",
        "thinking": "tilt", "surprised": "point", "concerned": "nod",
    }[emotion]
    return text, {"emotion": emotion, "gesture": gesture, "intensity": 0.65}


class ExhibitionApp:
    """Single-kiosk, privacy-first session kept only in process memory."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.state = PersonaState(
            name=config["name"],
            pronoun=config["pronoun"],
            user_nickname=config["user_nickname"],
            mood=config["mood"],
            current_interest=config["current_interest"],
            relationship_depth=int(config.get("relationship_depth", 1)),
        )
        self.history: list[dict[str, str]] = []
        self.lock = threading.Lock()
        self.providers = create_providers(config)
        requested = os.getenv("PERSONA_PROVIDER", str(config.get("default_provider", "ollama")))
        self.provider_id = requested if requested in self.providers else next(iter(self.providers))
        self.voicevox = VoicevoxClient(config.get("voicevox", {}))
        self.transcriber = FasterWhisperTranscriber(config.get("whisper", {}))
        self.smart_turn = SmartTurnDetector(config.get("smart_turn", {}))
        self.access_token = os.getenv("EXHIBITION_ACCESS_TOKEN", "")
        self.admin_token = os.getenv("EXHIBITION_ADMIN_TOKEN", "")
        self.request_times: dict[str, deque[float]] = defaultdict(deque)
        self.telemetry = Telemetry()
        self.warmup_report: dict[str, Any] = {"ready": False, "steps": {}}
        exhibition_config = config.get("exhibition", {})
        knowledge_path = exhibition_config.get("knowledge_path", "data/festival/knowledge.json")
        path = Path(knowledge_path)
        additional_paths = []
        for item in exhibition_config.get("additional_knowledge_paths", []):
            extra_path = Path(item)
            additional_paths.append(extra_path if extra_path.is_absolute() else ROOT / extra_path)
        self.festival_guide = FestivalKnowledgeBase(
            path if path.is_absolute() else ROOT / path,
            additional_paths=additional_paths,
        )
        self.activity_lock = threading.Lock()
        self.conversation_activity_until = 0.0

    @property
    def ready(self) -> bool:
        return self.provider.status().ready

    @property
    def provider(self) -> ModelProvider:
        return self.providers[self.provider_id]

    def warmup(self) -> dict[str, Any]:
        """Load local models before the first visitor starts a conversation."""
        started = time.perf_counter()
        steps: dict[str, Any] = {}
        audio = b""

        def run_step(name: str, operation: Any) -> Any:
            step_started = time.perf_counter()
            try:
                value = operation()
                steps[name] = {
                    "ready": True,
                    "durationMs": round((time.perf_counter() - step_started) * 1000, 1),
                }
                return value
            except Exception as exc:
                steps[name] = {
                    "ready": False,
                    "durationMs": round((time.perf_counter() - step_started) * 1000, 1),
                    "reason": str(exc),
                }
                return None

        if self.voicevox.status().ready:
            audio = run_step(
                "voice",
                lambda: self.voicevox.synthesize("海城祭の案内を始めます。", emotion="neutral", intensity=0.5),
            ) or b""
        else:
            steps["voice"] = {"ready": False, "reason": "音声エンジンが未準備です。"}
        if audio:
            run_step("transcribing", lambda: self.transcriber.transcribe(audio, "audio/wav"))
            run_step("turn", lambda: self.smart_turn.predict(audio, "audio/wav"))
        else:
            steps["transcribing"] = {"ready": False, "reason": "ウォームアップ音声がありません。"}
            steps["turn"] = {"ready": False, "reason": "ウォームアップ音声がありません。"}
        if self.provider_id == "ollama" and self.provider.status().ready:
            run_step(
                "model",
                lambda: self.provider.generate(
                    "ウォームアップ確認です。READYとのみ答えてください。",
                    [{"role": "user", "content": "準備確認"}],
                    4,
                    0.0,
                ),
            )
        elif self.provider_id == "ollama":
            steps["model"] = {"ready": False, "reason": self.provider.status().reason}
        else:
            steps["model"] = {"ready": True, "skipped": True, "reason": "クラウドAPIはウォームアップしません。"}
        self.warmup_report = {
            "ready": all(bool(item.get("ready")) for item in steps.values()),
            "durationMs": round((time.perf_counter() - started) * 1000, 1),
            "steps": steps,
        }
        return self.warmup_report

    def bootstrap(self) -> dict[str, Any]:
        exhibition = self.config.get("exhibition", {})
        statuses = [provider.status().to_dict() for provider in self.providers.values()]
        current = next(status for status in statuses if status["id"] == self.provider_id)
        voice_status = self.voicevox.status()
        stt_status = self.transcriber.status()
        turn_status = self.smart_turn.status()
        now = datetime.now(JAPAN_TIMEZONE)
        return {
            "name": self.state.name,
            "title": exhibition.get("title", "対話AI展示"),
            "suggestions": exhibition.get("suggestions", []),
            "ready": current["ready"],
            "setupIssue": current["reason"],
            "provider": self.provider_id,
            "providers": statuses,
            "voice": {
                "engine": self.voicevox.engine_type if voice_status.ready else "browser",
                "label": self.voicevox.engine_label,
                "ready": voice_status.ready,
                "version": voice_status.version,
                "reason": voice_status.reason,
                "speakerId": self.voicevox.speaker_id,
            },
            "stt": {
                "engine": "faster-whisper",
                "ready": stt_status.ready,
                "model": stt_status.model,
                "device": stt_status.device,
                "computeType": stt_status.compute_type,
                "reason": stt_status.reason,
            },
            "turnDetection": {
                "engine": "pipecat-smart-turn-v3.2",
                "ready": turn_status.ready,
                "model": turn_status.model,
                "reason": turn_status.reason,
            },
            "guide": self.festival_guide.status(),
            "clock": {
                "timeZone": "Asia/Tokyo",
                "serverNow": now.isoformat(timespec="seconds"),
            },
            "warmup": self.warmup_report,
        }

    def select_provider(self, provider_id: str) -> dict[str, Any]:
        if provider_id not in self.providers:
            raise ValueError("未対応のAI接続です。")
        with self.lock:
            self.provider_id = provider_id
            self.history.clear()
        status = self.provider.status()
        return status.to_dict()

    def reset(self) -> None:
        with self.lock:
            self.history.clear()

    def set_conversation_active(self, active: bool) -> None:
        with self.activity_lock:
            self.conversation_activity_until = time.monotonic() + 20 if active else 0.0

    def conversation_active(self) -> bool:
        with self.activity_lock:
            return self.conversation_activity_until > time.monotonic()

    def admin_snapshot(self) -> dict[str, Any]:
        data = self.telemetry.snapshot()
        provider_status = self.provider.status()
        voice_status = self.voicevox.status()
        stt_status = self.transcriber.status()
        turn_status = self.smart_turn.status()
        data["services"] = {
            "ai": {"ready": provider_status.ready, "label": provider_status.label, "detail": provider_status.model},
            "speech": {"ready": voice_status.ready, "label": self.voicevox.engine_label, "detail": voice_status.version or voice_status.reason},
            "whisper": {"ready": stt_status.ready, "label": "faster-whisper", "detail": f"{stt_status.model} / {stt_status.device} / {stt_status.compute_type}"},
            "turn": {"ready": turn_status.ready, "label": "Smart Turn", "detail": turn_status.model},
            "guide": {
                "ready": self.festival_guide.ready,
                "label": "文化祭パンフレット",
                "detail": f"{len(self.festival_guide.records)}件" if self.festival_guide.ready else self.festival_guide.load_error,
            },
        }
        data["provider"] = self.provider_id
        data["historyMessages"] = len(self.history)
        data["conversationActive"] = self.conversation_active()
        data["guide"] = self.festival_guide.status()
        return data

    def search_festival(self, query: str, limit: int = 6) -> dict[str, Any]:
        return {
            "query": query,
            "guide": self.festival_guide.status(),
            "results": records_to_json(self.festival_guide.search(query, limit=limit)),
        }

    def guide_cards(self, query: str, answer: str, limit: int = 3) -> list[dict[str, str]]:
        cards: list[dict[str, str]] = []
        for record in self.festival_guide.select_for_answer(query, answer, limit=limit):
            record_id = str(record.get("id", ""))
            if not record_id:
                continue
            title = str(record.get("event_name", "海城祭案内"))
            location = str(record.get("location", "記載なし"))
            page = str(record.get("page", "")).strip()
            source = f"パンフレットp.{page}" if page else str(record.get("source_label", "公式資料"))
            cards.append({
                "id": record_id,
                "imageUrl": f"/api/guide/card?id={quote(record_id, safe='')}",
                "alt": f"{title}。場所: {location}。出典: {source}",
            })
        return cards

    def is_turn_complete(self, text: str) -> bool:
        candidate = text.strip()
        if not candidate:
            return False
        with self.lock:
            context = self.history[-6:]

        normalized = re.sub(r"\s+", "", candidate)
        incomplete_endings = (
            "けど", "けれど", "けれども", "から", "ので", "て", "で", "し", "たり",
            "というか", "えっと", "あの", "その", "それで", "あと", "例えば",
            "について", "は", "が", "を", "に", "へ", "と", "も", "の",
        )
        if re.search(r"[。！？!?]$", normalized):
            return True
        if normalized in {"はい", "いいえ", "うん", "いや", "ありがとう", "お願い", "やめて"}:
            return True
        if any(normalized.endswith(ending) for ending in (
            "教えて", "案内して", "どこ", "いつ", "何時", "ある", "ない", "できる",
            "買える", "行ける", "おすすめ", "オススメ", "知りたい", "お願い",
        )):
            return True
        if normalized.endswith(incomplete_endings):
            return False

        detector = self.providers.get("ollama")
        if detector and detector.status().ready:
            prompt = (
                "あなたは日本語音声対話の発話終了判定器です。会話履歴を踏まえ、候補発話が意味として完結し、"
                "相手が自然に返答できるなら COMPLETE、まだ言い淀み・列挙・説明・接続表現の途中なら "
                "INCOMPLETE とだけ出力してください。質問、命令、短い相槌も完結していれば COMPLETE です。"
            )
            context_text = json.dumps(context, ensure_ascii=False)
            try:
                result = detector.generate(
                    prompt,
                    [{"role": "user", "content": f"会話履歴: {context_text}\n候補発話: {candidate}"}],
                    8,
                    0.0,
                ).upper()
                if "INCOMPLETE" in result:
                    return False
                if "COMPLETE" in result:
                    return True
            except ProviderError:
                pass

        return len(normalized) >= 3

    def allow_chat_request(self, client_id: str, *, limit: int = 12, window_seconds: int = 60) -> bool:
        now = time.monotonic()
        entries = self.request_times[client_id]
        while entries and entries[0] <= now - window_seconds:
            entries.popleft()
        if len(entries) >= limit:
            return False
        entries.append(now)
        return True

    def chat(self, user_text: str) -> str:
        return self.chat_reply(user_text)["answer"]

    def chat_reply(self, user_text: str) -> dict[str, Any]:
        result: dict[str, Any] | None = None
        for event in self.chat_reply_stream(user_text):
            if event.get("type") == "done":
                result = {key: value for key, value in event.items() if key != "type"}
        if result is None:
            raise ProviderError("AIから回答完了通知が返りませんでした。")
        return result

    def _build_chat_prompt(self, text: str) -> tuple[str, bool]:
        current_time = datetime.now(JAPAN_TIMEZONE)
        system_prompt = build_system_prompt(
                self.state,
                "展示モードのため、来場者ごとの長期記憶は保存・参照しない。",
            ) + f"""

## 現在日時
現在は {format_ai_current_time(current_time)}。
日付・曜日・時刻に関する回答は、この日本時間を基準にすること。
秒は推測せず、必要な場合も分単位で答えること。

## アバター演技指定（展示画面専用）
回答の先頭に、必ず次の形式の制御行を1行だけ付けること。
[[emotion:EMOTION|gesture:GESTURE|intensity:0.7]]
EMOTIONは neutral, happy, excited, thinking, surprised, concerned のいずれか。
GESTUREは nod, tilt, wave, point, cheer のいずれか。
intensityは0.3〜1.0。本文の感情と動作に自然に合う値を選ぶ。
制御行について本文で説明しないこと。
"""
        grounded = self.festival_guide.should_ground(text)
        if grounded:
            guide_context = self.festival_guide.build_context(text, now=current_time)
            if guide_context:
                system_prompt += "\n\n" + guide_context
            else:
                system_prompt += """

## 文化祭案内モード
文化祭知識ベースを現在利用できない。企画名・場所・日時を推測して答えず、
「パンフレットを確認できないため受付または公式サイトで確認してほしい」と案内すること。
"""
        return system_prompt, grounded

    def chat_reply_stream(self, user_text: str) -> Iterator[dict[str, Any]]:
        text = user_text.strip()
        if not text:
            raise ValueError("メッセージを入力してください。")
        guard = inspect_input(text)
        if not guard.allowed:
            raise ValueError(guard.reason)
        status = self.provider.status()
        if not status.ready:
            raise RuntimeError(status.reason or "選択したAIの準備ができていません。")

        with self.lock:
            self.history.append({"role": "user", "content": text})
            limit = int(self.config.get("exhibition", {}).get("session_message_limit", 20))
            self.history = self.history[-limit:]
            committed = False
            try:
                system_prompt, grounded = self._build_chat_prompt(text)
                raw_parts: list[str] = []
                pending = ""
                prefix_resolved = False
                animation_sent = False
                for chunk in self.provider.generate_stream(
                    system_prompt,
                    self.history,
                    int(self.config.get("max_tokens", 700)),
                    float(self.config.get("temperature", 0.8)),
                ):
                    raw_parts.append(chunk)
                    if not prefix_resolved:
                        pending += chunk
                        stripped = pending.lstrip()
                        if stripped.startswith("[[") and "]]" not in stripped:
                            continue
                        if stripped in {"[", "[["}:
                            continue
                        visible, early_animation = parse_animation_directive(pending)
                        prefix_resolved = True
                        yield {"type": "animation", "animation": early_animation}
                        animation_sent = True
                        if visible:
                            yield {"type": "delta", "text": visible}
                        continue
                    if chunk:
                        yield {"type": "delta", "text": chunk}
                raw_answer = "".join(raw_parts)
            except BaseException:
                if not committed and self.history and self.history[-1].get("role") == "user":
                    self.history.pop()
                raise
            answer, animation = parse_animation_directive(raw_answer)
            if not answer:
                answer = "ん？ もう一度聞かせてくれる？"
            if grounded:
                answer = self.festival_guide.ensure_requested_details(text, answer)
            if not animation_sent:
                yield {"type": "animation", "animation": animation}
            self.history.append({"role": "assistant", "content": answer})
            self.history = self.history[-limit:]
            committed = True
            yield {
                "type": "done",
                "answer": answer,
                "animation": animation,
                "guideCards": self.guide_cards(text, answer) if grounded else [],
            }


class Handler(BaseHTTPRequestHandler):
    app: ExhibitionApp

    def log_message(self, format: str, *args: object) -> None:
        message = format % args
        if "/invite/" in message:
            message = message.split("/invite/", 1)[0] + "/invite/[REDACTED]"
        if "/admin/" in message:
            message = message.split("/admin/", 1)[0] + "/admin/[REDACTED]"
        print(f"[web] {self.address_string()} {message}")

    def do_GET(self) -> None:
        self.app.telemetry.hit()
        parsed_path = urlparse(self.path)
        clean_path = parsed_path.path
        if clean_path.startswith("/admin/"):
            supplied = clean_path.removeprefix("/admin/")
            if self.app.admin_token and secrets.compare_digest(supplied, self.app.admin_token):
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/admin.html")
                self.send_header(
                    "Set-Cookie",
                    f"exhibition_admin={self.app.admin_token}; Path=/; Max-Age=43200; HttpOnly; Secure; SameSite=Strict",
                )
                self._security_headers()
                self.end_headers()
            else:
                self._not_found()
            return
        admin_paths = {"/admin.html", "/admin.css", "/admin.js", "/api/admin", "/api/admin/activity"}
        if clean_path in admin_paths:
            if not self._admin_authorized():
                self._not_found()
                return
            if clean_path == "/api/admin":
                self._json(self.app.admin_snapshot())
            elif clean_path == "/api/admin/activity":
                self._json({"conversationActive": self.app.conversation_active()})
            else:
                self._serve_static(clean_path)
            return
        if self.path.startswith("/invite/"):
            supplied = self.path.split("?", 1)[0].removeprefix("/invite/")
            if self.app.access_token and secrets.compare_digest(supplied, self.app.access_token):
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/")
                self.send_header(
                    "Set-Cookie",
                    f"exhibition_access={self.app.access_token}; Path=/; Max-Age=43200; HttpOnly; Secure; SameSite=Strict",
                )
                self._security_headers()
                self.end_headers()
            else:
                self._not_found()
            return
        if not self._authorized():
            self._not_found()
            return
        if self.path == "/api/bootstrap":
            self._json(self.app.bootstrap())
            return
        if clean_path == "/api/guide/search":
            params = parse_qs(parsed_path.query)
            query = str(params.get("q", [""])[0]).strip()
            if not query:
                self._json({"error": "検索語を指定してください。"}, status=HTTPStatus.BAD_REQUEST)
                return
            self._json(self.app.search_festival(query))
            return
        if clean_path == "/api/guide/card":
            params = parse_qs(parsed_path.query)
            record_id = str(params.get("id", [""])[0]).strip()
            record = self.app.festival_guide.get_record(record_id)
            if not record:
                self._not_found()
                return
            festival = str(self.app.festival_guide.metadata.get("festival_name", "第135代 海城祭"))
            self._svg(render_guide_card_svg(record, festival))
            return
        path = "/index.html" if self.path == "/" else self.path.split("?", 1)[0]
        self._serve_static(path)

    def _serve_static(self, path: str) -> None:
        relative = path.lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in target.parents or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        self.app.telemetry.hit()
        if not self._authorized():
            self._not_found()
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if self.path == "/api/transcribe":
                if length > 8_000_000:
                    raise ValueError("録音データが大きすぎます。20秒以内で話してください。")
                client_id = (self.headers.get("CF-Connecting-IP") or self.client_address[0]) + ":stt"
                if not self.app.allow_chat_request(client_id, limit=60):
                    self._json({"error": "音声認識の回数が上限に達しました。"}, status=HTTPStatus.TOO_MANY_REQUESTS)
                    return
                audio = self.rfile.read(length)
                with self.app.telemetry.measure("transcribing") as timer:
                    text = self.app.transcriber.transcribe(audio, self.headers.get("Content-Type", "audio/webm"))
                self._json({"text": text, "timings": {"transcribing": timer.duration_ms}})
                return
            if self.path == "/api/analyze-turn":
                if length > 8_000_000:
                    raise ValueError("録音データが大きすぎます。")
                client_id = (self.headers.get("CF-Connecting-IP") or self.client_address[0]) + ":turn-audio"
                if not self.app.allow_chat_request(client_id, limit=30):
                    self._json({"error": "発話判定の回数が上限に達しました。"}, status=HTTPStatus.TOO_MANY_REQUESTS)
                    return
                audio = self.rfile.read(length)
                content_type = self.headers.get("Content-Type", "audio/webm")
                with self.app.telemetry.measure("transcribing") as transcription_timer:
                    try:
                        text = self.app.transcriber.transcribe(audio, content_type)
                    except ValueError as exc:
                        if "声を認識できませんでした" not in str(exc):
                            raise
                        text = ""
                with self.app.telemetry.measure("judging") as judging_timer:
                    if not text:
                        complete = False
                        probability = None
                        engine = "no-speech"
                    else:
                        try:
                            complete, probability = self.app.smart_turn.predict(audio, content_type)
                            engine = "pipecat-smart-turn-v3.2"
                        except SmartTurnError:
                            complete = self.app.is_turn_complete(text)
                            probability = None
                            engine = "text-fallback"
                self._json({
                    "text": text,
                    "complete": complete,
                    "probability": probability,
                    "engine": engine,
                    "timings": {
                        "transcribing": transcription_timer.duration_ms,
                        "judging": judging_timer.duration_ms,
                    },
                })
                return
            if length > 50_000:
                raise ValueError("リクエストが大きすぎます。")
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/chat-stream":
                client_id = self.headers.get("CF-Connecting-IP") or self.client_address[0]
                if not self.app.allow_chat_request(client_id):
                    self._json(
                        {"error": "短時間の送信回数が上限に達しました。1分ほど待ってください。"},
                        status=HTTPStatus.TOO_MANY_REQUESTS,
                    )
                    return
                self._chat_stream(str(body.get("message", "")))
                return
            if self.path == "/api/chat":
                client_id = self.headers.get("CF-Connecting-IP") or self.client_address[0]
                if not self.app.allow_chat_request(client_id):
                    self._json(
                        {"error": "短時間の送信回数が上限に達しました。1分ほど待ってください。"},
                        status=HTTPStatus.TOO_MANY_REQUESTS,
                    )
                    return
                with self.app.telemetry.measure("thinking") as timer:
                    reply = self.app.chat_reply(str(body.get("message", "")))
                reply["timings"] = {"thinking": timer.duration_ms}
                self._json(reply)
            elif self.path == "/api/voice":
                client_id = (self.headers.get("CF-Connecting-IP") or self.client_address[0]) + ":voice"
                if not self.app.allow_chat_request(client_id, limit=20):
                    self._json({"error": "音声生成の回数が上限に達しました。"}, status=HTTPStatus.TOO_MANY_REQUESTS)
                    return
                with self.app.telemetry.measure("synthesizing") as timer:
                    audio = self.app.voicevox.synthesize(
                        str(body.get("text", "")),
                        emotion=str(body.get("emotion", "neutral")),
                        intensity=body.get("intensity", 0.65),
                    )
                self._audio(audio, timer.duration_ms)
            elif self.path == "/api/provider":
                self._json(self.app.select_provider(str(body.get("provider", ""))))
            elif self.path == "/api/conversation-state":
                active = body.get("active")
                if not isinstance(active, bool):
                    raise ValueError("会話状態が不正です。")
                self.app.set_conversation_active(active)
                self._json({"ok": True, "conversationActive": self.app.conversation_active()})
            elif self.path == "/api/turn-state":
                client_id = (self.headers.get("CF-Connecting-IP") or self.client_address[0]) + ":turn"
                if not self.app.allow_chat_request(client_id, limit=30):
                    self._json({"error": "発話判定の回数が上限に達しました。"}, status=HTTPStatus.TOO_MANY_REQUESTS)
                    return
                with self.app.telemetry.measure("judging") as timer:
                    complete = self.app.is_turn_complete(str(body.get("text", "")))
                self._json({"complete": complete, "timings": {"judging": timer.duration_ms}})
            elif self.path == "/api/reset":
                self.app.reset()
                self._json({"ok": True})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except ProviderError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
        except VoicevoxError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
        except TranscriptionError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
        except SmartTurnError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
        except RuntimeError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
        except Exception as exc:
            print(f"[error] {type(exc).__name__}: {exc}")
            self._json(
                {"error": "うまく応答できませんでした。少し待って、もう一度試してください。"},
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )

    def _chat_stream(self, message: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self._security_headers()
        self.end_headers()
        started = time.perf_counter()
        first_delta_ms: float | None = None
        try:
            with self.app.telemetry.measure("thinking"):
                for event in self.app.chat_reply_stream(message):
                    if event.get("type") == "delta" and first_delta_ms is None:
                        first_delta_ms = round((time.perf_counter() - started) * 1000, 1)
                    if event.get("type") == "done":
                        event["timings"] = {
                            "thinking": round((time.perf_counter() - started) * 1000, 1),
                            "firstToken": first_delta_ms,
                        }
                    self._ndjson(event)
        except (BrokenPipeError, ConnectionResetError):
            return
        except (ValueError, ProviderError, RuntimeError) as exc:
            try:
                self._ndjson({"type": "error", "error": str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                pass
        except Exception as exc:
            print(f"[stream-error] {type(exc).__name__}: {exc}")
            try:
                self._ndjson({"type": "error", "error": "回答のストリーミング中にエラーが発生しました。"})
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _ndjson(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
        self.wfile.write(data)
        self.wfile.flush()

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _audio(self, data: bytes, duration_ms: float | None = None) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if duration_ms is not None:
            self.send_header("X-Process-Duration-Ms", str(duration_ms))
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _svg(self, data: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=300")
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        if not self.app.access_token:
            return True
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        supplied = cookie.get("exhibition_access")
        return bool(supplied and secrets.compare_digest(supplied.value, self.app.access_token))

    def _admin_authorized(self) -> bool:
        if not self.app.admin_token:
            return True
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        supplied = cookie.get("exhibition_admin")
        return bool(supplied and secrets.compare_digest(supplied.value, self.app.admin_token))

    def _not_found(self) -> None:
        data = b"Not Found"
        self.send_response(HTTPStatus.NOT_FOUND)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _security_headers(self) -> None:
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")


class ExhibitionHTTPServer(ThreadingHTTPServer):
    # Windowsで古い展示サーバーと同じポートを共有しない。
    allow_reuse_address = False


def make_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    config = load_config()
    ensure_voicevox_engine(config.get("voicevox", {}))
    app = ExhibitionApp(config)
    report = app.warmup()
    print(f"ウォームアップ: {json.dumps(report, ensure_ascii=False)}", flush=True)
    Handler.app = app
    return ExhibitionHTTPServer((host, port), Handler)


def main() -> None:
    server = make_server()
    print("展示画面: http://127.0.0.1:8765")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
