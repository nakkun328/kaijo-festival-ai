from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


SCHEMA = {
    "type": "object",
    "properties": {
        "page_title": {"type": "string"},
        "page_summary": {"type": "string"},
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["event", "schedule", "food", "facility", "rule", "navigation", "overview"]},
                    "event_name": {"type": "string", "maxLength": 80},
                    "organization": {"type": "string", "maxLength": 60},
                    "category": {"type": "string", "maxLength": 30},
                    "location": {"type": "string", "maxLength": 80},
                    "date": {"type": "string", "maxLength": 20},
                    "day": {"type": "string", "maxLength": 20},
                    "start_time": {"type": "string", "maxLength": 10},
                    "end_time": {"type": "string", "maxLength": 10},
                    "description": {"type": "string", "maxLength": 120},
                    "keywords": {"type": "array", "maxItems": 6, "items": {"type": "string", "maxLength": 20}},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["kind", "event_name", "organization", "category", "location", "date", "day", "start_time", "end_time", "description", "keywords", "confidence"],
            },
            "maxItems": 14,
        },
    },
    "required": ["page_title", "page_summary", "records"],
}

PROMPT = """あなたは日本語の文化祭パンフレットを正確にデータ化する担当者です。
添付画像の文字を読み、来場者案内に役立つ事実をJSONへ抽出してください。

- 企画、展示、食品、ステージ演目、時刻表の各行、施設、移動案内、注意事項を別レコードにする。
- 公式の企画名・団体名・教室番号・号館・日付・開始終了時刻を見たまま転記する。
- 書かれていない情報を補完・推測しない。読めない欄は空文字にし confidence を下げる。
- 時刻は可能なら HH:MM。土曜日・日曜日の区別を day に残す。
- 1ページ最大14レコード。説明は80文字以内、keywordsは最大6個とし、簡潔にする。
- 一覧ページでは個々の企画を大量に転記せず、分類ごとのoverviewを最大3件にまとめる。
- 広告だけのページは records を空にしてよい。
- ページ番号は呼び出し側が付与するのでJSONへ含めない。
"""


def average_hash(path: Path) -> tuple[bool, ...]:
    with Image.open(path) as image:
        pixels = list(image.convert("L").resize((32, 32)).get_flattened_data())
    mean = sum(pixels) / len(pixels)
    return tuple(pixel > mean for pixel in pixels)


def render_pdf(pdf: Path, page_dir: Path, pdftoppm: str) -> list[Path]:
    page_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(page_dir.glob("page-*.jpg"))
    if existing:
        return existing
    prefix = page_dir / "page"
    subprocess.run([pdftoppm, "-jpeg", "-r", "150", str(pdf), str(prefix)], check=True)
    return sorted(page_dir.glob("page-*.jpg"))


def ollama_extract(image_path: Path, model: str, base_url: str) -> dict[str, Any]:
    image = base64.b64encode(image_path.read_bytes()).decode("ascii")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": PROMPT, "images": [image]}],
        "format": SCHEMA,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 3600},
        "keep_alive": "30m",
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return json.loads(payload["message"]["content"])


def main() -> int:
    parser = argparse.ArgumentParser(description="文化祭パンフレットをOllama Visionで構造化する")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/festival/knowledge.json"))
    parser.add_argument("--page-dir", type=Path, default=Path("tmp/pdfs/festival-pages-ocr"))
    parser.add_argument("--pdftoppm", default="pdftoppm")
    parser.add_argument("--model", default="gemma4:12b")
    parser.add_argument("--ollama", default="http://127.0.0.1:11434")
    parser.add_argument("--min-confidence", type=float, default=0.55)
    parser.add_argument("--first-page", type=int, default=1)
    parser.add_argument("--last-page", type=int)
    args = parser.parse_args()

    pdf = args.pdf.resolve()
    if not pdf.is_file():
        parser.error(f"PDFがありません: {pdf}")
    pages = render_pdf(pdf, args.page_dir.resolve(), args.pdftoppm)
    last_page = args.last_page or len(pages)
    seen_hashes: list[tuple[bool, ...]] = []
    records: list[dict[str, Any]] = []
    page_summaries: list[dict[str, Any]] = []

    for page_number, image_path in enumerate(pages, start=1):
        if page_number < args.first_page or page_number > last_page:
            continue
        fingerprint = average_hash(image_path)
        if any(sum(left != right for left, right in zip(fingerprint, old)) <= 3 for old in seen_hashes):
            print(f"p.{page_number}: duplicate, skipped", flush=True)
            continue
        seen_hashes.append(fingerprint)
        print(f"p.{page_number}: extracting...", flush=True)
        try:
            page = ollama_extract(image_path, args.model, args.ollama)
        except Exception as exc:
            print(f"p.{page_number}: ERROR {exc}", file=sys.stderr, flush=True)
            continue
        page_summaries.append({
            "page": page_number,
            "title": str(page.get("page_title", "")).strip(),
            "summary": str(page.get("page_summary", "")).strip(),
        })
        for index, item in enumerate(page.get("records", []), start=1):
            if not isinstance(item, dict) or float(item.get("confidence", 0)) < args.min_confidence:
                continue
            item["id"] = f"p{page_number:02d}-{index:02d}"
            item["page"] = page_number
            item["page_title"] = str(page.get("page_title", "")).strip()
            records.append(item)

    payload = {
        "metadata": {
            "festival_name": "第135回 海城祭",
            "festival_dates": ["2026-09-19", "2026-09-20"],
            "source_file": pdf.name,
            "source_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "source_pages": len(pages),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "extractor": f"Ollama {args.model} vision",
            "review_status": "AI抽出済み・重要な日時と場所は原本画像で要確認",
        },
        "pages": page_summaries,
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(records)} records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
