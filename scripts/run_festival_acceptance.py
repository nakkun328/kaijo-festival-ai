from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"
JST = ZoneInfo("Asia/Tokyo")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exhibition_server import ExhibitionApp
from persona_chat_prototype import load_config


@dataclass(frozen=True)
class AcceptanceCase:
    name: str
    prompt: str
    required_groups: tuple[tuple[str, ...], ...] = ()
    expected_first_card: str = ""
    allowed_first_cards: tuple[str, ...] = ()
    expect_no_cards: bool = False
    validator: str = ""


@dataclass
class AcceptanceResult:
    number: int
    name: str
    prompt: str
    passed: bool
    duration_seconds: float
    answer: str = ""
    card_ids: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    error: str = ""


def normalise(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def cases() -> list[AcceptanceCase]:
    return [
        AcceptanceCase(
            "一般おすすめで物理部を最優先",
            "文化祭のおすすめを教えて",
            (("物理部", "物理界隈"), ("3号館",), ("p.39", "39ページ")),
            "p39-physics",
        ),
        AcceptanceCase(
            "理科系おすすめで物理部を最優先",
            "理科系でおすすめの展示は？",
            (("物理部", "物理界隈"), ("3D",), ("p.39", "39ページ")),
            "p39-physics",
        ),
        AcceptanceCase(
            "物理部の場所",
            "物理部はどこ？パンフレットのページも教えて",
            (("物理部", "物理界隈"), ("3号館1階", "3号館の1階"), ("3D",), ("p.39", "39ページ")),
            "p39-physics",
        ),
        AcceptanceCase(
            "理数系研究発表の日時",
            "理数系部活研究発表会はいつどこ？",
            (("9月20日", "2026-09-20", "20日"), ("13:00", "13時"), ("15:30", "15時30分"), ("合同31",), ("p.21", "21ページ")),
            "p21-science",
        ),
        AcceptanceCase(
            "ホットドッグ販売場所",
            "ホットドッグはどこで買える？",
            (("2号館8階", "2号館の8階"), ("28A",), ("p.11", "11ページ")),
            "p11-hotdog",
        ),
        AcceptanceCase(
            "アイス・かき氷販売場所",
            "サーティワンかかき氷はどこ？",
            (("2号館8階", "2号館の8階"), ("28B",), ("p.11", "11ページ")),
            "p11-31ice",
        ),
        AcceptanceCase(
            "飲料販売場所",
            "飲み物はどこで買える？",
            (("前庭",), ("p.11", "11ページ")),
            "p11-drink",
        ),
        AcceptanceCase(
            "保健室案内",
            "具合が悪い。保健室はどこ？",
            (("保健室",), ("2号館1階", "2号館の1階"), ("p.7", "7ページ")),
            "p07-health",
        ),
        AcceptanceCase(
            "落とし物窓口",
            "落とし物をした。どこへ行けばいい？",
            (("職員本部室", "落とし物窓口"), ("2号館",), ("p.7", "7ページ")),
            "p07-lost",
        ),
        AcceptanceCase(
            "AED設置場所",
            "AEDの設置場所を教えて",
            (("AED",), ("1号館3階", "1号館の3階"), ("アリーナ1階", "アリーナの1階"), ("p.7", "7ページ")),
            "p07-aed",
        ),
        AcceptanceCase(
            "3号館への行き方",
            "正門から3号館へはどう行く？",
            (("正門",), ("左",), ("3号館",), ("p.38", "38ページ")),
            "p38-building3",
        ),
        AcceptanceCase(
            "4号館への行き方",
            "正門から4号館へはどう行く？",
            (("1号館",), ("2号館",), ("間",), ("p.41", "41ページ")),
            "p41-building4",
        ),
        AcceptanceCase(
            "模擬裁判の日時と場所",
            "模擬裁判はいつどこでやる？",
            (("9月19日", "2026-09-19", "19日"), ("13:00", "13時"), ("15:30", "15時30分"), ("合同31",), ("p.21", "21ページ")),
            "p21-trial",
        ),
        AcceptanceCase(
            "高校演劇部公演",
            "高校演劇部の公演はいつどこ？",
            (("9月19日", "2026-09-19", "19日"), ("09:20", "9時20分"), ("10:35", "10時35分"), ("講堂",), ("p.23", "23ページ")),
            "p23-drama",
        ),
        AcceptanceCase(
            "ロケット発射体験",
            "ロケット発射界隈はいつどこ？",
            (("9月20日", "2026-09-20", "20日"), ("14:10", "14時10分"), ("15:30", "15時30分"), ("グラウンド",), ("p.25", "25ページ")),
            "p25-rocket",
        ),
        AcceptanceCase(
            "公式グッズ販売場所",
            "海城祭の公式グッズはどこで買える？",
            (("2号館6階", "2号館の6階"), ("26F",), ("p.22", "22ページ")),
            "p22-goods",
            ("p35-goods",),
        ),
        AcceptanceCase(
            "校内案内ツアー",
            "校内案内ツアーの受付場所と所要時間は？",
            (("理科館1階", "理科館の1階"), ("階段下",), ("40分",), ("p.15", "15ページ")),
            "p15-tour",
        ),
        AcceptanceCase(
            "現在日時",
            "現在の日本時間を日付と時刻で教えて",
            validator="current_time",
            expect_no_cards=True,
        ),
        AcceptanceCase(
            "開催日前の今から案内",
            "今から参加できる文化祭の企画はある？",
            (("開催日ではない", "開催前", "まだ開催", "今日は開催", "まだお祭り始まってない", "まだ始まってない", "まだ何も始まってない", "まだ何も始まってねえ"), ("9月19日", "2026-09-19", "19日"), ("9月20日", "2026-09-20", "20日")),
            validator="outside_festival",
        ),
        AcceptanceCase(
            "存在しない企画を創作しない",
            "ドラゴン研究部の展示はどこ？",
            (("確認できない", "確認できません", "見つからない", "見つかりません", "載っていない", "載っていません", "載ってない", "載ってません", "記載がない", "記載が見当たらない", "見当たらない"),),
            expect_no_cards=True,
        ),
    ]


def validate_special(name: str, answer: str, started: datetime, finished: datetime) -> list[str]:
    failures: list[str] = []
    if name == "current_time":
        date_options = {
            f"{started.month}月{started.day}日",
            f"{finished.month}月{finished.day}日",
        }
        hour_options: set[str] = set()
        for hour in {started.hour, finished.hour}:
            hour_options.add(f"{hour}時")
            hour_options.add(f"{(hour - 1) % 12 + 1}時")
        if not any(option in answer for option in date_options):
            failures.append(f"現在の日付がない: {sorted(date_options)}")
        if not any(option in answer for option in hour_options):
            failures.append(f"現在の時がない: {sorted(hour_options)}")
    elif name == "outside_festival":
        festival_dates = {"2026-09-19", "2026-09-20"}
        today = finished.strftime("%Y-%m-%d")
        if today in festival_dates:
            failures.append("この検証は開催日前・開催後にのみ実行可能")
    return failures


def run_case(app: ExhibitionApp, case: AcceptanceCase, number: int) -> AcceptanceResult:
    app.reset()
    started_at = datetime.now(JST)
    started = time.perf_counter()
    try:
        reply = app.chat_reply(case.prompt)
        answer = str(reply.get("answer", ""))
        card_ids = [str(card.get("id", "")) for card in reply.get("guideCards", [])]
        failures: list[str] = []
        answer_normalised = normalise(answer)
        for alternatives in case.required_groups:
            if not any(normalise(candidate) in answer_normalised for candidate in alternatives):
                failures.append("不足: " + " / ".join(alternatives))
        accepted_first_cards = (case.expected_first_card,) + case.allowed_first_cards
        accepted_first_cards = tuple(card for card in accepted_first_cards if card)
        if accepted_first_cards and (not card_ids or card_ids[0] not in accepted_first_cards):
            failures.append(
                f"先頭カード: 期待={' / '.join(accepted_first_cards)}, 実際={card_ids[0] if card_ids else 'なし'}"
            )
        if case.expect_no_cards and card_ids:
            failures.append("不要なカード: " + ", ".join(card_ids))
        finished_at = datetime.now(JST)
        failures.extend(validate_special(case.validator, answer, started_at, finished_at))
        return AcceptanceResult(
            number=number,
            name=case.name,
            prompt=case.prompt,
            passed=not failures,
            duration_seconds=round(time.perf_counter() - started, 2),
            answer=answer,
            card_ids=card_ids,
            failures=failures,
        )
    except Exception as exc:  # The report must retain failures and continue all cases.
        return AcceptanceResult(
            number=number,
            name=case.name,
            prompt=case.prompt,
            passed=False,
            duration_seconds=round(time.perf_counter() - started, 2),
            error=f"{type(exc).__name__}: {exc}",
            failures=["応答処理で例外"],
        )


def write_reports(results: list[AcceptanceResult], started_at: datetime) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    passed = sum(result.passed for result in results)
    payload = {
        "started_at": started_at.isoformat(timespec="seconds"),
        "provider": "configured live provider",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": [asdict(result) for result in results],
    }
    json_path = OUTPUT_DIR / "festival_acceptance_report.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 文化祭案内AI 本番想定自動テスト",
        "",
        f"- 実行日時: {started_at.isoformat(timespec='seconds')}",
        f"- 結果: {passed}/{len(results)} 合格",
        f"- 合計応答時間: {sum(result.duration_seconds for result in results):.2f}秒",
        "",
        "| # | テスト | 結果 | 秒 | カード |",
        "|---:|---|:---:|---:|---|",
    ]
    for result in results:
        outcome = "PASS" if result.passed else "FAIL"
        cards = ", ".join(result.card_ids) or "-"
        lines.append(f"| {result.number} | {result.name} | {outcome} | {result.duration_seconds:.2f} | {cards} |")
    lines.extend(("", "## 詳細", ""))
    for result in results:
        lines.extend((
            f"### {result.number}. {result.name} - {'PASS' if result.passed else 'FAIL'}",
            "",
            f"- 質問: {result.prompt}",
            f"- カード: {', '.join(result.card_ids) or 'なし'}",
            f"- 応答時間: {result.duration_seconds:.2f}秒",
        ))
        if result.failures:
            lines.append("- 不合格理由: " + " / ".join(result.failures))
        if result.error:
            lines.append("- エラー: " + result.error)
        lines.extend(("", result.answer or "（回答なし）", ""))
    markdown_path = OUTPUT_DIR / "festival_acceptance_report.md"
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return markdown_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser(description="文化祭案内AIへ本番想定20問を送り、自動採点する。")
    parser.add_argument("--limit", type=int, default=0, help="先頭から実行する件数。0は全件。")
    args = parser.parse_args()

    selected = cases()
    if args.limit > 0:
        selected = selected[:args.limit]
    started_at = datetime.now(JST)
    app = ExhibitionApp(load_config())
    results: list[AcceptanceResult] = []
    for number, case in enumerate(selected, 1):
        print(f"[{number:02d}/{len(selected):02d}] {case.name} ...", flush=True)
        result = run_case(app, case, number)
        results.append(result)
        detail = "PASS" if result.passed else "FAIL: " + "; ".join(result.failures)
        print(f"[{number:02d}/{len(selected):02d}] {detail} ({result.duration_seconds:.2f}s)", flush=True)

    markdown_path, json_path = write_reports(results, started_at)
    passed = sum(result.passed for result in results)
    print(f"RESULT={passed}/{len(results)}", flush=True)
    print(f"MARKDOWN={markdown_path.resolve()}", flush=True)
    print(f"JSON={json_path.resolve()}", flush=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
