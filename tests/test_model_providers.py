import os
import unittest
from unittest.mock import MagicMock, patch

from model_providers import GeminiProvider, OllamaProvider, OpenAIProvider, create_providers


class ProviderTests(unittest.TestCase):
    def test_cloud_provider_status_depends_on_key(self):
        provider = OpenAIProvider("openai", {"label": "OpenAI", "model": "test"})
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(provider.status().ready)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret"}, clear=True):
            self.assertTrue(provider.status().ready)

    def test_registry_builds_supported_providers(self):
        providers = create_providers({
            "providers": {
                "openai": {"label": "OpenAI", "model": "a"},
                "gemini": {"label": "Gemini", "model": "b"},
            }
        })
        self.assertIsInstance(providers["gemini"], GeminiProvider)

    def test_ollama_stream_yields_incremental_text(self):
        provider = OllamaProvider("ollama", {
            "label": "Ollama", "model": "test", "base_url": "http://local", "keep_alive": "12h",
        })
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_lines.return_value = [
            '{"message":{"content":"こん"},"done":false}',
            '{"message":{"content":"にちは。"},"done":false}',
            '{"message":{"content":""},"done":true}',
        ]
        with patch("model_providers.httpx.stream", return_value=response) as stream:
            chunks = list(provider.generate_stream("system", [{"role": "user", "content": "やあ"}], 50, 0.2))
        self.assertEqual(chunks, ["こん", "にちは。"])
        self.assertTrue(stream.call_args.kwargs["json"]["stream"])
        self.assertEqual(stream.call_args.kwargs["json"]["keep_alive"], "12h")
        response.raise_for_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
