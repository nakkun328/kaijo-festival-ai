"""Conservative suggestions for durable, non-sensitive user facts.

Suggestions are never saved as memories without an explicit approval action.
"""
from __future__ import annotations

import re


SENSITIVE = re.compile(
    r'パスワード|暗証番号|住所|電話番号|メールアドレス|クレジットカード|口座|借金|年収|'
    r'病気|病名|診断|薬|服薬|自傷|自殺|宗教|支持政党|選挙', re.IGNORECASE)
STABLE_FACT = re.compile(
    r'^(?:(?:私は|僕は|俺は|自分は).{2,100}(?:が好き|を続けている|に取り組んでいる|'
    r'を勉強している|を練習している)|.{2,100}を(?:続けている|練習している|勉強している))$')


def memory_candidate(text: str) -> str | None:
    candidate = text.strip().rstrip('。！!').strip()
    if not 8 <= len(candidate) <= 120 or '?' in candidate or '？' in candidate:
        return None
    if SENSITIVE.search(candidate) or not STABLE_FACT.fullmatch(candidate):
        return None
    return candidate
