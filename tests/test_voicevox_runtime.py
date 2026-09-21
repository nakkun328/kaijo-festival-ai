import unittest
from unittest.mock import patch

import voicevox_runtime


class VoicevoxRuntimeTests(unittest.TestCase):
    @patch("voicevox_runtime._engine_ready", return_value=True)
    @patch("voicevox_runtime.subprocess.Popen")
    def test_running_engine_is_reused(self, popen, _ready):
        self.assertTrue(voicevox_runtime.ensure_voicevox_engine({}))
        popen.assert_not_called()

    @patch("voicevox_runtime._engine_ready", return_value=False)
    def test_missing_engine_returns_false(self, _ready):
        self.assertFalse(voicevox_runtime.ensure_voicevox_engine({"engine_path": "tools/missing/run.exe"}))

    @patch("voicevox_runtime.time.sleep")
    @patch("voicevox_runtime._engine_ready", side_effect=[False, True])
    @patch("voicevox_runtime.subprocess.Popen")
    def test_aivisspeech_uses_configured_local_port(self, popen, _ready, _sleep):
        config = {
            "engine": "aivisspeech",
            "base_url": "http://127.0.0.1:10101",
            "engine_path": "tools/aivisspeech-engine/Windows-x64/run.exe",
        }
        self.assertTrue(voicevox_runtime.ensure_voicevox_engine(config))
        arguments = popen.call_args.args[0]
        self.assertIn("10101", arguments)
        self.assertIn("--disable_mutable_api", arguments)

    @patch("voicevox_runtime.time.sleep")
    @patch("voicevox_runtime._engine_ready", side_effect=[False, True])
    @patch("voicevox_runtime.subprocess.Popen")
    def test_coeiroink_uses_its_fixed_local_api(self, popen, ready, _sleep):
        config = {
            "engine": "coeiroink",
            "base_url": "http://127.0.0.1:50032",
            "engine_path": "tools/coeiroink/engine/COEIROINK_WIN_CPU_v.2.13.0/engine/engine.exe",
        }
        self.assertTrue(voicevox_runtime.ensure_voicevox_engine(config))
        self.assertEqual(popen.call_args.args[0], [str(voicevox_runtime.DEFAULT_COEIROINK_ENGINE)])
        self.assertEqual(popen.call_args.kwargs["cwd"], voicevox_runtime.DEFAULT_COEIROINK_ENGINE.parent.parent)
        self.assertEqual(ready.call_args_list[0].args[1], "coeiroink")


if __name__ == "__main__":
    unittest.main()
