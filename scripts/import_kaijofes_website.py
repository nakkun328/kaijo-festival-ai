from __future__ import annotations

import argparse
import html
import json
import re
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


TOP_URL = "https://www.kaijofes.com/"
BOOTHS_URL = "https://www.kaijofes.com/booths"
DEFAULT_OUTPUT = Path("data/festival/website_knowledge.json")
USER_AGENT = "KaijoFestivalGuide/1.0 (official-site knowledge updater)"


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.in_script = False
        self.current: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "script":
            self.in_script = True
            self.current = []

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self.in_script:
            self.scripts.append("".join(self.current))
            self.in_script = False
            self.current = []


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def extract_booths(document: str) -> list[dict[str, Any]]:
    collector = _ScriptCollector()
    collector.feed(document)
    decoder = json.JSONDecoder()
    for script in collector.scripts:
        match = re.fullmatch(r"\s*self\.__next_f\.push\((.*)\)\s*", script, re.DOTALL)
        if not match:
            continue
        try:
            flight_item = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(flight_item, list) or len(flight_item) < 2 or not isinstance(flight_item[1], str):
            continue
        payload = flight_item[1]
        marker = '"booths":'
        position = payload.find(marker)
        if position < 0:
            continue
        booths, _ = decoder.raw_decode(payload[position + len(marker):])
        if isinstance(booths, list) and booths:
            return [item for item in booths if isinstance(item, dict)]
    raise ValueError("公式サイトの企画データを見つけられませんでした。ページ構造が変わった可能性があります。")


def _plain_text(document: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", document, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def extract_overview(document: str) -> dict[str, Any]:
    text = _plain_text(document)
    date_match = re.search(
        r"(20\d{2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*-\s*(\d{1,2})\s*\.\s*(\d{1,2})",
        text,
    )
    time_match = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", text)
    if not date_match or not time_match:
        raise ValueError("公式サイトから開催日または開催時間を読み取れませんでした。")
    year, start_month, start_day, end_month, end_day = (int(value) for value in date_match.groups())
    dates = (
        f"{year:04d}-{start_month:02d}-{start_day:02d}",
        f"{year:04d}-{end_month:02d}-{end_day:02d}",
    )
    address_match = re.search(r"〒\d{3}-\d{4}\s+[^#]+?(?=Google Map|135th Kaijo fes)", text)
    return {
        "festival_name": "第135代 海城祭",
        "festival_dates": list(dates),
        "start_time": time_match.group(1),
        "end_time": time_match.group(2),
        "address": address_match.group(0).strip() if address_match else "東京都新宿区大久保3-6-1",
    }


def _location_label(locations: Any) -> str:
    labels: list[str] = []
    for location in locations if isinstance(locations, list) else []:
        if not isinstance(location, dict):
            continue
        building = str(location.get("building") or "").strip()
        floor = location.get("floor")
        floor_label = f"{floor}階" if isinstance(floor, int) and floor > 0 else ""
        name = str(location.get("name") or "").strip()
        label = "".join((building, floor_label))
        if name and name not in label:
            label = f"{label} {name}".strip()
        if label and label not in labels:
            labels.append(label)
    return "／".join(labels)


def _record(booth: dict[str, Any], overview: dict[str, Any], *, day_key: str | None = None) -> dict[str, Any]:
    booth_id = str(booth.get("id") or "").strip()
    dates = overview["festival_dates"]
    held_saturday = bool(booth.get("heldOnSaturday"))
    held_sunday = bool(booth.get("heldOnSunday"))
    suffix = f"-{day_key}" if day_key else ""
    if day_key == "sat":
        date, day = dates[0], "土"
        start, end = booth.get("saturdayStart"), booth.get("saturdayEnd")
    elif day_key == "sun":
        date, day = dates[1], "日"
        start, end = booth.get("sundayStart"), booth.get("sundayEnd")
    else:
        selected_dates = [dates[0]] if held_saturday else []
        selected_days = ["土"] if held_saturday else []
        if held_sunday:
            selected_dates.append(dates[1])
            selected_days.append("日")
        date, day = "・".join(selected_dates), "・".join(selected_days)
        start = booth.get("saturdayStart") or booth.get("sundayStart")
        end = booth.get("saturdayEnd") or booth.get("sundayEnd")
    title = str(booth.get("title") or "").strip()
    organization = str(booth.get("organization") or "").strip()
    section = str(booth.get("section") or "企画").strip()
    return {
        "id": f"web-{booth_id}{suffix}",
        "kind": "food" if section == "食品" else "event",
        "event_name": title,
        "organization": organization,
        "category": section,
        "location": _location_label(booth.get("locations")),
        "date": date,
        "day": day,
        "start_time": str(start or ""),
        "end_time": str(end or ""),
        "description": str(booth.get("description") or "").strip(),
        "keywords": [value for value in (booth_id, title, organization, section) if value],
        "confidence": 1.0,
        "page": "",
        "page_title": "海城祭公式サイト 企画情報",
        "source_type": "official_website",
        "source_label": "海城祭公式サイト",
        "source_url": BOOTHS_URL,
    }


def convert_booths(booths: list[dict[str, Any]], overview: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for booth in booths:
        booth_id = str(booth.get("id") or "").strip()
        if not booth_id or not str(booth.get("title") or "").strip():
            continue
        saturday_times = (booth.get("saturdayStart"), booth.get("saturdayEnd"))
        sunday_times = (booth.get("sundayStart"), booth.get("sundayEnd"))
        split_days = (
            bool(booth.get("heldOnSaturday"))
            and bool(booth.get("heldOnSunday"))
            and saturday_times != sunday_times
            and any(saturday_times + sunday_times)
        )
        if split_days:
            records.append(_record(booth, overview, day_key="sat"))
            records.append(_record(booth, overview, day_key="sun"))
        else:
            records.append(_record(booth, overview))
    return records


def build_payload(top_document: str, booths_document: str) -> dict[str, Any]:
    overview = extract_overview(top_document)
    booths = extract_booths(booths_document)
    records = convert_booths(booths, overview)
    overview_record = {
        "id": "web-overview",
        "kind": "overview",
        "event_name": overview["festival_name"],
        "organization": "海城中学校・高等学校",
        "category": "開催概要",
        "location": overview["address"],
        "date": "・".join(overview["festival_dates"]),
        "day": "土・日",
        "start_time": overview["start_time"],
        "end_time": overview["end_time"],
        "description": "公式サイト掲載の開催概要。テーマはNoroshi（のろし）。",
        "keywords": ["開催日", "開場", "閉場", "アクセス", "住所", "Noroshi", "のろし"],
        "confidence": 1.0,
        "page": "",
        "page_title": "海城祭公式サイト トップページ",
        "source_type": "official_website",
        "source_label": "海城祭公式サイト",
        "source_url": TOP_URL,
    }
    return {
        "metadata": {
            "festival_name": overview["festival_name"],
            "festival_dates": overview["festival_dates"],
            "source_file": BOOTHS_URL,
            "source_urls": [TOP_URL, BOOTHS_URL],
            "generated_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds"),
            "extractor": "公式サイトの公開ページから決定的に抽出",
            "review_status": "公式サイトから自動取得（回答時に出典を明示）",
        },
        "records": [overview_record, *records],
    }


def update_knowledge(output: Path = DEFAULT_OUTPUT) -> int:
    payload = build_payload(fetch_text(TOP_URL), fetch_text(BOOTHS_URL))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    return len(payload["records"])


def main() -> int:
    parser = argparse.ArgumentParser(description="海城祭公式サイトの企画情報を知識JSONへ変換する。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-html", type=Path, help="ネット取得せず保存済みトップHTMLを使う。")
    parser.add_argument("--booths-html", type=Path, help="ネット取得せず保存済み企画HTMLを使う。")
    args = parser.parse_args()
    if args.top_html or args.booths_html:
        if not args.top_html or not args.booths_html:
            parser.error("--top-html と --booths-html は同時に指定してください。")
        payload = build_payload(
            args.top_html.read_text(encoding="utf-8"),
            args.booths_html.read_text(encoding="utf-8"),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(args.output)
        count = len(payload["records"])
    else:
        count = update_knowledge(args.output)
    print(f"{count} records -> {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
