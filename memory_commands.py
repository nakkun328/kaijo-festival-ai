"""Conservative, explicit Japanese memory commands."""
from __future__ import annotations

import re

SAVE_ENDING = re.compile(r'(?:を)?(?:覚えて(?:おいて|て)|記憶して(?:おいて|て)|保存して)(?:ね|ください)?[。！!\s]*$')
FORGET_ENDING = re.compile(r'(?:を)?(?:忘れて|記憶から消して)(?:ね|ください)?[。！!\s]*$')
DEICTIC = {'これ', 'それ', 'このこと', 'そのこと', 'さっきのこと', '今の話'}
PROPOSAL_QUESTION = 'これ、覚えておく？'
PROPOSAL_YES = {'うん', 'はい', 'いいよ', 'お願い', 'うんお願い', 'うん、お願い'}
PROPOSAL_NO = {'いいえ', 'いや', '今はいい', '今は覚えない', '覚えなくていい'}


def proposal_reply(text: str, history: list[dict], pending: dict | None) -> str | None:
    if not pending or not history or history[-1].get('role') != 'assistant':
        return None
    if not history[-1].get('content', '').rstrip().endswith(PROPOSAL_QUESTION):
        return None
    reply = text.strip().rstrip('。！!').strip()
    if reply in PROPOSAL_YES:
        return 'save'
    if reply in PROPOSAL_NO:
        return 'dismiss'
    return None


def parse_memory_command(text: str) -> tuple[str, str] | None:
    candidate = text.strip()
    if match := SAVE_ENDING.search(candidate):
        return 'save', candidate[:match.start()].strip(' 、。！!をは:：') or 'これ'
    if match := FORGET_ENDING.search(candidate):
        target = candidate[:match.start()].strip(' 、。！!をは:：')
        target = target.removesuffix('もう').strip(' 、。！!をは:：')
        return 'forget', target or 'それ'
    return None


def resolve_memory_action(command: tuple[str, str], history: list[dict], memories: list[dict]) -> dict:
    intent, target = command
    if intent == 'save':
        if target in DEICTIC:
            recent_user = [item['content'].strip() for item in history[-8:]
                           if item['role'] == 'user' and not parse_memory_command(item['content'])]
            if not recent_user:
                return {'question':'何を覚えておけばいい？ 内容を具体的に教えて。'}
            target = recent_user[-1]
            if len(target) < 4 or re.search(r'[?？]|(?:教えて|整理して|まとめて|どう思う|考えて|手伝って)[。！!\s]*$', target):
                return {'question':'直前の返事のどの内容を覚える？ 覚えたい文を具体的に教えて。'}
        if len(target) > 2000:
            return {'question':'覚えておく内容を少し短くして教えて。'}
        return {'action':'save', 'content':target}
    if target in DEICTIC:
        if history and history[-1].get('role') == 'assistant':
            confirmation = re.fullmatch(r'覚えたよ。「(.+)」', history[-1].get('content', '').strip())
            if confirmation:
                exact = [item for item in memories if item['content'] == confirmation.group(1)]
                if len(exact) == 1:
                    return {'action':'delete', 'id':exact[0]['id'], 'content':exact[0]['content']}
        return {'question':'どの記憶を忘れる？ 内容を少し具体的に教えて。'}
    normalized = target.removesuffix('のこと').strip()
    matches = [item for item in memories if normalized in item['content']]
    if len(matches) == 1:
        return {'action':'delete', 'id':matches[0]['id'], 'content':matches[0]['content']}
    if len(matches) > 1:
        return {'question':'同じ言葉を含む記憶が複数あるよ。「覚えていること」から選んで削除して。'}
    return {'question':'その内容の記憶が見つからなかった。覚えていることを開いて確認してみて。'}
