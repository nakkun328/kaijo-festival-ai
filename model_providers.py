from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Iterator

import httpx

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    id: str
    label: str
    model: str
    ready: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProviderError(RuntimeError):
    pass


def _request_json(
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 90,
) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8"))
            error = body.get("error", body)
            detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        except Exception:
            pass
        raise ProviderError(f"APIエラー {exc.code}: {detail or exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderError(f"接続できません: {getattr(exc, 'reason', exc)}") from exc


class ModelProvider:
    def __init__(self, provider_id: str, config: dict[str, Any]):
        self.id = provider_id
        self.config = config
        self.label = str(config["label"])
        self.model = str(os.getenv(f"{provider_id.upper()}_MODEL", config["model"]))

    def status(self) -> ProviderStatus:
        raise NotImplementedError

    def generate(self, system: str, messages: list[dict[str, str]], max_tokens: int, temperature: float) -> str:
        raise NotImplementedError

    def generate_stream(
        self, system: str, messages: list[dict[str, str]], max_tokens: int, temperature: float
    ) -> Iterator[str]:
        answer = self.generate(system, messages, max_tokens, temperature)
        if answer:
            yield answer


class OllamaProvider(ModelProvider):
    def __init__(self, provider_id: str, config: dict[str, Any]):
        super().__init__(provider_id, config)
        self.base_url = str(os.getenv("OLLAMA_BASE_URL", config.get("base_url", "http://127.0.0.1:11434"))).rstrip("/")
        self.keep_alive = str(config.get("keep_alive", "24h"))

    def status(self) -> ProviderStatus:
        try:
            data = _request_json(f"{self.base_url}/api/tags", timeout=2)
            installed = [item.get("name", "") for item in data.get("models", [])]
            matching = self.model in installed or any(name.split(":", 1)[0] == self.model for name in installed)
            if not installed:
                reason = f"Ollamaは起動中ですがモデルがありません。ollama pull {self.model} を実行してください。"
                return ProviderStatus(self.id, self.label, self.model, False, reason)
            if not matching:
                return ProviderStatus(
                    self.id, self.label, self.model, False,
                    f"モデル {self.model} がありません。ollama pull {self.model} を実行してください。",
                )
            return ProviderStatus(self.id, self.label, self.model, True)
        except ProviderError:
            return ProviderStatus(
                self.id, self.label, self.model, False,
                "Ollamaが見つかりません。インストールして起動してください。",
            )

    def generate(self, system: str, messages: list[dict[str, str]], max_tokens: int, temperature: float) -> str:
        data = _request_json(
            f"{self.base_url}/api/chat",
            payload={
                "model": self.model,
                "messages": [{"role": "system", "content": system}, *messages],
                "stream": False,
                "think": False,
                "keep_alive": self.keep_alive,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
        )
        answer = str(data.get("message", {}).get("content", "")).strip()
        if not answer:
            raise ProviderError("ローカルAIから本文が返りませんでした。モデル設定を確認してください。")
        return answer

    def generate_stream(
        self, system: str, messages: list[dict[str, str]], max_tokens: int, temperature: float
    ) -> Iterator[str]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": True,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        yielded = False
        try:
            with httpx.stream("POST", f"{self.base_url}/api/chat", json=payload, timeout=90) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise ProviderError(str(data["error"]))
                    chunk = str(data.get("message", {}).get("content", ""))
                    if chunk:
                        yielded = True
                        yield chunk
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Ollamaのストリーミング接続に失敗しました: {exc}") from exc
        if not yielded:
            raise ProviderError("ローカルAIから本文が返りませんでした。モデル設定を確認してください。")


class OpenAIProvider(ModelProvider):
    def status(self) -> ProviderStatus:
        ready = bool(os.getenv("OPENAI_API_KEY"))
        reason = "OPENAI_API_KEY が未設定です。" if not ready else ""
        return ProviderStatus(self.id, self.label, self.model, ready, reason)

    def generate(self, system: str, messages: list[dict[str, str]], max_tokens: int, temperature: float) -> str:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise ProviderError("OPENAI_API_KEY が未設定です。")
        data = _request_json(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            payload={
                "model": self.model,
                "instructions": system,
                "input": messages,
                "max_output_tokens": max_tokens,
                "reasoning": {"effort": "none"},
                "store": False,
            },
        )
        texts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    texts.append(str(content.get("text", "")))
        return "\n".join(texts).strip()


class GeminiProvider(ModelProvider):
    def status(self) -> ProviderStatus:
        ready = bool(os.getenv("GEMINI_API_KEY"))
        reason = "GEMINI_API_KEY が未設定です。" if not ready else ""
        return ProviderStatus(self.id, self.label, self.model, ready, reason)

    def generate(self, system: str, messages: list[dict[str, str]], max_tokens: int, temperature: float) -> str:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise ProviderError("GEMINI_API_KEY が未設定です。")
        contents = [
            {"role": "model" if item["role"] == "assistant" else "user", "parts": [{"text": item["content"]}]}
            for item in messages
        ]
        data = _request_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            payload={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": contents,
                "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
            },
        )
        candidates = data.get("candidates", [])
        if not candidates:
            raise ProviderError("Geminiから回答が返りませんでした。安全設定または利用上限を確認してください。")
        parts = candidates[0].get("content", {}).get("parts", [])
        return "\n".join(str(part.get("text", "")) for part in parts if "text" in part).strip()


class AnthropicProvider(ModelProvider):
    def status(self) -> ProviderStatus:
        if anthropic is None:
            return ProviderStatus(self.id, self.label, self.model, False, "Anthropicライブラリが未導入です。")
        ready = bool(os.getenv("ANTHROPIC_API_KEY"))
        return ProviderStatus(
            self.id, self.label, self.model, ready,
            "ANTHROPIC_API_KEY が未設定です。" if not ready else "",
        )

    def generate(self, system: str, messages: list[dict[str, str]], max_tokens: int, temperature: float) -> str:
        if anthropic is None or not os.getenv("ANTHROPIC_API_KEY"):
            raise ProviderError("Anthropicの接続準備ができていません。")
        response = anthropic.Anthropic().messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
        )
        return "\n".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()


PROVIDER_TYPES = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
}


def create_providers(config: dict[str, Any]) -> dict[str, ModelProvider]:
    return {
        provider_id: PROVIDER_TYPES[provider_id](provider_id, provider_config)
        for provider_id, provider_config in config["providers"].items()
        if provider_id in PROVIDER_TYPES
    }
