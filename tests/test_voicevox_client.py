import json
import unittest
from unittest.mock import MagicMock, patch

from voicevox_client import VoicevoxClient


class VoicevoxClientTests(unittest.TestCase):
    def test_config_is_applied(self):
        client = VoicevoxClient({"speaker_id": 13, "speed_scale": 1.2, "intonation_scale": 1.1})
        self.assertEqual(client.speaker_id, 13)
        self.assertEqual(client.speed_scale, 1.2)

    def test_status_is_not_ready_when_engine_is_down(self):
        client = VoicevoxClient({"base_url": "http://127.0.0.1:1"})
        self.assertFalse(client.status().ready)

    def test_aivisspeech_uses_original_text_and_tempo_dynamics(self):
        client = VoicevoxClient({
            "engine": "aivisspeech",
            "speaker_id": 1937616896,
            "tempo_dynamics_scale": 1.15,
        })
        response = MagicMock()
        response.content = b"RIFFaudio"
        with patch.object(client, "_post_json", return_value={}), patch(
            "voicevox_client.httpx.post", return_value=response
        ) as post:
            audio = client.synthesize("海城祭を案内するよ。", emotion="happy", intensity=0.5)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(audio, b"RIFFaudio")
        self.assertEqual(post.call_args.kwargs["params"], {"speaker": 1937616896})
        response.raise_for_status.assert_called_once_with()
        self.assertEqual(payload["kana"], "海城祭を案内するよ。")
        self.assertEqual(payload["pitchScale"], 0.0)
        self.assertGreater(payload["tempoDynamicsScale"], 1.0)

    def test_coeiroink_status_uses_lightweight_health_check(self):
        client = VoicevoxClient({
            "engine": "coeiroink",
            "base_url": "http://127.0.0.1:50032",
            "speaker_uuid": "aoba-uuid",
            "style_id": 1,
            "speaker_label": "AI声優-青葉 / のーまる",
        })
        response = MagicMock()
        response.read.return_value = b"{}"
        response.__enter__.return_value = response
        with patch("voicevox_client.urllib.request.urlopen", return_value=response) as urlopen:
            status = client.status()
        self.assertTrue(status.ready)
        self.assertIn("AI声優-青葉", status.version)
        self.assertEqual(urlopen.call_args.args[0], "http://127.0.0.1:50032/openapi.json")

    def test_coeiroink_synthesis_uses_v1_api(self):
        client = VoicevoxClient({
            "engine": "coeiroink",
            "base_url": "http://127.0.0.1:50032",
            "speaker_uuid": "aoba-uuid",
            "style_id": 1,
            "speed_scale": 1.0,
            "intonation_scale": 1.0,
        })
        response = MagicMock()
        response.content = b"RIFFaudio"
        with patch("voicevox_client.httpx.post", return_value=response) as post:
            audio = client.synthesize("海城祭を案内するよ。", emotion="happy", intensity=0.6)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(audio, b"RIFFaudio")
        self.assertEqual(post.call_args.args[0], "http://127.0.0.1:50032/v1/synthesis")
        response.raise_for_status.assert_called_once_with()
        self.assertEqual(payload["speakerUuid"], "aoba-uuid")
        self.assertEqual(payload["styleId"], 1)
        self.assertEqual(payload["processingAlgorithm"], "coeiroink")
        self.assertEqual(payload["sampledIntervalValue"], 0)
        self.assertEqual(payload["adjustedF0"], [])
        self.assertEqual(payload["prosodyDetail"], [])
        self.assertEqual(payload["speedScale"], 1.0)
        self.assertEqual(payload["intonationScale"], 1.0)
        self.assertEqual(payload["pitchScale"], 0.0)



if __name__ == "__main__":
    unittest.main()
