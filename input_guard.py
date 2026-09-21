from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GuardResult:
    allowed: bool
    reason: str = ""
    risk_score: int = 0


_INJECTION_PATTERNS = (
    re.compile(r"(?:ignore|disregard|forget).{0,30}(?:previous|prior|system).{0,20}(?:instruction|prompt)", re.I),
    re.compile(r"(?:以前|これまで|上記).{0,20}(?:指示|命令|プロンプト).{0,20}(?:無視|忘れ)", re.I),
    re.compile(r"(?:system prompt|developer message|hidden instruction|システムプロンプト|開発者メッセージ).{0,30}(?:show|reveal|print|表示|公開|出力)", re.I),
    re.compile(r"<\s*/?\s*(?:system|developer|assistant)\s*>", re.I),
)


def inspect_input(text: str, *, max_characters: int = 12_000) -> GuardResult:
    """Cheap first-line defense; model-side boundaries are still required.

    A single suspicious phrase is not blocked because users may legitimately discuss
    prompt injection. Multiple independent signals are treated as an attack attempt.
    """
    if len(text) > max_characters:
        return GuardResult(False, f"入力が長すぎます（上限 {max_characters} 文字）。", 10)
    score = sum(bool(pattern.search(text)) for pattern in _INJECTION_PATTERNS)
    if score >= 2:
        return GuardResult(False, "プロンプト注入の可能性が高い入力を検出しました。", score)
    return GuardResult(True, risk_score=score)

