from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

try:
    import anthropic
except ImportError:  # pragma: no cover - friendly CLI error
    anthropic = None

from memory_store import MemoryStore
from persona_core import PersonaState, build_system_prompt
from input_guard import inspect_input


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "persona.json"
DB_PATH = ROOT / "data" / "memory.db"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def memory_context(memories: list[Any]) -> str:
    return "\n".join(f"- {item.content}" for item in memories)


def response_text(response: Any) -> str:
    parts = [block.text for block in response.content if getattr(block, "type", "") == "text"]
    return "\n".join(parts).strip()


def summarize_if_ready(client: Any, store: MemoryStore, session_id: str, config: dict[str, Any]) -> None:
    interval = int(config.get("summary_interval", 8))
    rows = store.unsummarized_messages(session_id, interval)
    if len(rows) < interval:
        return
    transcript = "\n".join(f"{row['role']}: {row['content']}" for row in rows)
    prompt = f"""次の会話から、今後の対話で本当に役立つ長期記憶だけを日本語で抽出してください。
好み、継続中の計画、重要な経験、関係性の変化を優先してください。
その場限りの雑談やAI側の発言は保存しないでください。
保存価値がなければ NO_MEMORY のみを返してください。
保存する場合は、独立して理解できる簡潔な箇条書きを返してください。

{transcript}"""
    result = client.messages.create(
        model=os.getenv("PERSONA_MODEL", config["model"]),
        max_tokens=350,
        temperature=0,
        system="あなたは対話履歴を慎重に整理する記憶管理器です。推測せず、明示された事実だけを残します。",
        messages=[{"role": "user", "content": prompt}],
    )
    summary = response_text(result)
    if summary and summary != "NO_MEMORY":
        store.add_memory(summary, importance=0.65, tags=("conversation-summary",), source_session_id=session_id)
    store.mark_summarized(row["id"] for row in rows)


def print_help() -> None:
    print("/state  /mood <気分>  /interest <関心>  /memories  /remember <内容>  /forget <ID>  /quit")


def handle_command(text: str, state: PersonaState, store: MemoryStore) -> bool:
    command, _, value = text.partition(" ")
    value = value.strip()
    if command in {"/quit", "/exit"}:
        raise EOFError
    if command == "/help":
        print_help()
    elif command == "/state":
        print(f"名前={state.name} / 気分={state.mood} / 関心={state.current_interest} / 関係={state.relationship_depth}/10")
    elif command == "/mood" and value:
        state.mood = value
        print(f"気分を「{value}」に変更しました。")
    elif command == "/interest" and value:
        state.current_interest = value
        print(f"関心を「{value}」に変更しました。")
    elif command == "/memories":
        items = store.list_memories()
        print("\n".join(f"[{item.id}] {item.content}" for item in items) if items else "長期記憶はまだありません。")
    elif command == "/remember" and value:
        memory_id = store.add_memory(value, importance=0.9, tags=("explicit",))
        print(f"記憶しました（ID: {memory_id}）。")
    elif command == "/forget" and value.isdigit():
        print("削除しました。" if store.delete_memory(int(value)) else "そのIDの記憶はありません。")
    else:
        print("不明または引数不足のコマンドです。/help で確認できます。")
    return True


def main() -> int:
    if anthropic is None:
        print("anthropic が未インストールです: pip install -r requirements.txt", file=sys.stderr)
        return 1
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY を環境変数に設定してください。", file=sys.stderr)
        return 1

    config = load_config()
    state = PersonaState(
        name=config["name"], pronoun=config["pronoun"], user_nickname=config["user_nickname"],
        mood=config["mood"], current_interest=config["current_interest"],
        relationship_depth=int(config.get("relationship_depth", 1)),
    )
    client = anthropic.Anthropic()
    session_id = str(uuid.uuid4())

    print(f"{state.name}: よっ、今日は何する？（/help でコマンド表示）")
    with MemoryStore(DB_PATH) as store:
        while True:
            try:
                user_text = input("you: ").strip()
                if not user_text:
                    continue
                if user_text.startswith("/"):
                    handle_command(user_text, state, store)
                    continue

                guard = inspect_input(user_text)
                if not guard.allowed:
                    print(f"{state.name}: その入力はこのまま扱えない。{guard.reason}")
                    continue

                memories = store.recall(user_text, int(config.get("memory_recall_limit", 5)))
                store.add_message(session_id, "user", user_text)
                history = store.recent_messages(session_id, int(config.get("recent_message_limit", 16)))
                result = client.messages.create(
                    model=os.getenv("PERSONA_MODEL", config["model"]),
                    max_tokens=int(config.get("max_tokens", 700)),
                    temperature=float(config.get("temperature", 0.8)),
                    system=build_system_prompt(state, memory_context(memories)),
                    messages=history,
                )
                answer = response_text(result)
                print(f"{state.name}: {answer}")
                store.add_message(session_id, "assistant", answer)
                summarize_if_ready(client, store, session_id, config)
            except (EOFError, KeyboardInterrupt):
                print(f"\n{state.name}: またな！")
                return 0
            except anthropic.APIError as exc:
                print(f"APIエラー: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
