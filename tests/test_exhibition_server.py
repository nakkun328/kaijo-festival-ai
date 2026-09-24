import unittest
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from exhibition_server import (
    ExhibitionApp,
    format_ai_current_time,
    parse_model_json_object,
    parse_animation_directive,
    render_guide_card_svg,
)
from model_providers import ProviderStatus
from voicevox_client import VoicevoxStatus


CONFIG = {
    "name": "リク",
    "pronoun": "俺",
    "user_nickname": "お前",
    "mood": "元気",
    "current_interest": "展示",
    "model": "test-model",
    "default_provider": "openai",
    "providers": {
        "openai": {"label": "OpenAI", "model": "test-openai"},
        "gemini": {"label": "Gemini", "model": "test-gemini"},
    },
    "exhibition": {
        "title": "テスト展示",
        "suggestions": ["話そう"],
        "knowledge_path": "data/festival/missing-test-knowledge.json",
    },
}


class ExhibitionAppTests(unittest.TestCase):
    def test_model_json_accepts_only_trailing_commas_outside_strings(self):
        parsed = parse_model_json_object('```json\n{"title":"進路,}","options":["大学", "就職",],}\n```')
        self.assertEqual(parsed, {'title':'進路,}', 'options':['大学', '就職']})
        with self.assertRaises(ValueError):
            parse_model_json_object('{"title": unquoted}')

    def test_animation_directive_is_removed_and_validated(self):
        answer, animation = parse_animation_directive(
            "[[emotion:excited|gesture:cheer|intensity:0.9]]\nよし、やろう！"
        )
        self.assertEqual(answer, "よし、やろう！")
        self.assertEqual(animation, {"emotion": "excited", "gesture": "cheer", "intensity": 0.9})

    def test_animation_falls_back_from_answer_text(self):
        answer, animation = parse_animation_directive("それ最高！ すごい！")
        self.assertEqual(answer, "それ最高！ すごい！")
        self.assertEqual(animation["emotion"], "excited")
        self.assertEqual(animation["gesture"], "cheer")

    def test_bootstrap_contains_exhibition_identity(self):
        app = ExhibitionApp(CONFIG)
        data = app.bootstrap()
        self.assertEqual(data["name"], "リク")
        self.assertEqual(data["title"], "テスト展示")
        self.assertEqual(data["suggestions"], ["話そう"])
        self.assertIn("setupIssue", data)
        self.assertEqual(len(data["providers"]), 2)
        self.assertEqual(data["stt"]["engine"], "faster-whisper")
        self.assertEqual(data["stt"]["model"], "small")
        self.assertEqual(data["turnDetection"]["engine"], "pipecat-smart-turn-v3.2")
        self.assertIn("guide", data)
        self.assertEqual(data["clock"]["timeZone"], "Asia/Tokyo")
        self.assertRegex(data["clock"]["serverNow"], r"\+09:00$")

    def test_warmup_primes_local_voice_pipeline_without_calling_cloud_model(self):
        app = ExhibitionApp(CONFIG)
        app.voicevox.status = MagicMock(return_value=VoicevoxStatus(True, "test"))
        app.voicevox.synthesize = MagicMock(return_value=b"wave")
        app.transcriber.transcribe = MagicMock(return_value={"text": "海城祭の案内を始めます。"})
        app.smart_turn.predict = MagicMock(return_value={"complete": True})
        app.providers["openai"].generate = MagicMock()

        report = app.warmup()

        self.assertTrue(report["ready"])
        self.assertTrue(report["steps"]["model"]["skipped"])
        app.voicevox.synthesize.assert_called_once()
        app.transcriber.transcribe.assert_called_once_with(b"wave", "audio/wav")
        app.smart_turn.predict.assert_called_once_with(b"wave", "audio/wav")
        app.providers["openai"].generate.assert_not_called()
        self.assertEqual(app.bootstrap()["warmup"], report)

    def test_search_festival_is_safe_without_knowledge_file(self):
        app = ExhibitionApp(CONFIG)
        result = app.search_festival("物理部")
        self.assertIn("guide", result)
        self.assertEqual(result["results"], [])

    def test_reset_clears_ephemeral_history(self):
        app = ExhibitionApp(CONFIG)
        app.history = [{"role": "user", "content": "秘密"}]
        app.reset()
        self.assertEqual(app.history, [])

    def test_unready_app_has_clear_error(self):
        app = ExhibitionApp(CONFIG)
        with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
            app.chat("こんにちは")

    def test_selecting_provider_resets_history(self):
        app = ExhibitionApp(CONFIG)
        app.history = [{"role": "user", "content": "前の会話"}]
        result = app.select_provider("gemini")
        self.assertEqual(result["id"], "gemini")
        self.assertEqual(app.history, [])

    def test_turn_fallback_detects_connective_ending(self):
        app = ExhibitionApp(CONFIG)
        self.assertFalse(app.is_turn_complete("それについて考えてるんだけど"))
        self.assertFalse(app.is_turn_complete("物理部について"))
        self.assertTrue(app.is_turn_complete("場所を教えて"))
        self.assertTrue(app.is_turn_complete("それについてどう思う？"))

    def test_ambiguous_turn_uses_conversation_context_model(self):
        app = ExhibitionApp(CONFIG)
        detector = MagicMock()
        detector.status.return_value = ProviderStatus("ollama", "Ollama", "test", True)
        detector.generate.return_value = "INCOMPLETE"
        app.providers["ollama"] = detector
        app.history = [{"role": "assistant", "content": "どんな展示が好き？"}]

        self.assertFalse(app.is_turn_complete("科学系か音楽系か迷っています"))
        detector.generate.assert_called_once()
        prompt_messages = detector.generate.call_args.args[1]
        self.assertIn("どんな展示が好き", prompt_messages[0]["content"])

    def test_conversation_activity_expires_and_can_be_stopped(self):
        app = ExhibitionApp(CONFIG)
        self.assertFalse(app.conversation_active())
        app.set_conversation_active(True)
        self.assertTrue(app.conversation_active())
        app.set_conversation_active(False)
        self.assertFalse(app.conversation_active())

    def test_guide_card_svg_contains_only_escaped_verified_fields(self):
        svg = render_guide_card_svg({
            "event_name": "物理部 <実験>",
            "organization": "物理部",
            "category": "科学展示",
            "location": "3号館1階 3D",
            "date": "2026-09-20",
            "day": "日",
            "start_time": "10:00",
            "end_time": "15:00",
            "page": 39,
        }).decode("utf-8")
        self.assertIn("物理部 &lt;実験&gt;", svg)
        self.assertNotIn("物理部 <実験>", svg)
        self.assertIn("3号館1階 3D", svg)
        self.assertIn("p.39", svg)

    def test_ai_current_time_uses_japan_time_without_seconds(self):
        utc = datetime(2026, 9, 10, 23, 45, 37, tzinfo=ZoneInfo("UTC"))
        formatted = format_ai_current_time(utc)
        self.assertEqual(formatted, "2026年9月11日（金曜日）08:45（日本時間 / Asia/Tokyo）")
        self.assertNotIn("37", formatted)

    def test_chat_stream_removes_animation_directive_and_commits_history(self):
        app = ExhibitionApp(CONFIG)
        provider = MagicMock()
        provider.status.return_value = ProviderStatus("openai", "OpenAI", "test", True)
        provider.generate_stream.return_value = iter([
            "[[emotion:happy|gesture:wave|intensity:0.8]]\nこん",
            "にちは。案内するよ。",
        ])
        app.providers["openai"] = provider
        events = list(app.chat_reply_stream("こんにちは"))
        deltas = "".join(event["text"] for event in events if event["type"] == "delta")
        done = next(event for event in events if event["type"] == "done")
        self.assertEqual(deltas, "こんにちは。案内するよ。")
        self.assertEqual(done["answer"], "こんにちは。案内するよ。")
        self.assertEqual(done["animation"]["emotion"], "happy")
        self.assertEqual(app.history[-1], {"role": "assistant", "content": "こんにちは。案内するよ。"})


if __name__ == "__main__":
    unittest.main()
