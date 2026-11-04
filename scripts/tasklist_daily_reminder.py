#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def normalize_header(value: str | None) -> str:
    if value is None:
        return ""
    value = unicodedata.normalize("NFKC", value).strip().replace(" ", "").replace("　", "")
    return value.lower()


def build_export_url(raw_url: str) -> str:
    if not raw_url:
        raise ValueError("TASKLIST_SHEET_CSV_URL is not configured.")
    parsed = urllib.parse.urlparse(raw_url)
    if "/export" in parsed.path:
        return raw_url
    if "docs.google.com" not in parsed.netloc:
        raise ValueError(f"Google Sheets URLではありません: {raw_url}")
    match = re.search(r"/d/([^/]+)", parsed.path)
    if not match:
        raise ValueError(f"Google SheetsのIDをURLから抽出できません: {raw_url}")
    sheet_id = match.group(1)
    query = urllib.parse.parse_qs(parsed.query)
    export_query = {"format": "csv"}
    if parsed.query and "gid" in query:
        export_query["gid"] = query["gid"][0]
    elif parsed.fragment.startswith("gid="):
        export_query["gid"] = parsed.fragment.split("=", 1)[1]
    return urllib.parse.urlunparse(
        parsed._replace(
            path=f"/spreadsheets/d/{sheet_id}/export",
            query=urllib.parse.urlencode(export_query),
            fragment="",
        )
    )


def fetch_csv_text(url: str) -> str:
    request_url = build_export_url(url)
    req = urllib.request.Request(request_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis", "latin1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_date(raw_value: str | None) -> date | None:
    if raw_value is None:
        return None
    value = unicodedata.normalize("NFKC", str(raw_value)).strip()
    if not value:
        return None
    for fmt in (
        "%Y/%m/%d",
        "%Y-%m-%d",
        "%Y年%m月%d日",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def select_row_value(row: list[str], indexes: list[int], prefer_date: bool = False) -> str:
    candidates: list[str] = []
    for idx in indexes:
        if idx >= len(row):
            continue
        value = (row[idx] or "").strip()
        if value:
            candidates.append(value)

    if prefer_date:
        for value in candidates:
            if parse_date(value) is not None:
                return value
        for value in candidates:
            if re.search(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}", value):
                return value

    return candidates[0] if candidates else ""


def parse_sheet_rows(csv_text: str) -> list[dict[str, str]]:
    reader = csv.reader(io.StringIO(csv_text))
    rows = [row for row in reader if any((cell or "").strip() for cell in row)]
    if not rows:
        return []

    header_index = None
    required_cols = {"実施日", "タスク", "担当", "大分類"}
    for idx, row in enumerate(rows):
        normalized = [normalize_header(cell) for cell in row]
        if required_cols.issubset(set(normalized)):
            header_index = idx
            break
    if header_index is None:
        return []

    header = rows[header_index]
    header_map: dict[str, list[int]] = {key: [] for key in required_cols}
    for idx, cell in enumerate(header):
        key = normalize_header(cell)
        if key in required_cols:
            header_map[key].append(idx)

    if not required_cols.issubset(set(header_map)):
        return []

    parsed_rows: list[dict[str, str]] = []
    last_category = ""
    for row in rows[header_index + 1 :]:
        if not row:
            continue
        entry = {
            key: select_row_value(row, header_map[key], prefer_date=(key == "実施日"))
            for key in required_cols
        }

        category_value = (entry.get("大分類") or "").strip()
        if category_value:
            last_category = category_value
        elif last_category:
            entry["大分類"] = last_category

        if any((value or "").strip() for value in entry.values()):
            parsed_rows.append(entry)
    return parsed_rows


def extract_due_tasks(rows: Iterable[dict[str, str]], target_date: date) -> list[dict[str, object]]:
    due_tasks: list[dict[str, object]] = []
    for row in rows:
        date_raw = row.get("実施日", "")
        task_raw = row.get("タスク", "")
        assignee_raw = row.get("担当", "")
        category_raw = row.get("大分類", "")
        task_date = parse_date(date_raw)
        if task_date != target_date:
            continue
        task = task_raw.strip()
        if not task:
            continue
        due_tasks.append(
            {
                "task": task,
                "assignee": assignee_raw.strip(),
                "category": category_raw.strip(),
                "date": task_date,
            }
        )
    return due_tasks


def render_line_message(task_info: dict[str, object]) -> str:
    task = str(task_info["task"])
    assignee = str(task_info["assignee"] or "未設定")
    category = str(task_info["category"] or "未分類")
    return f"タスク：{task}\n担当：{assignee}\n分類：{category}\n"


def send_line_message(message: str, *, group_id_env: str = "LINE_GROUP_ID_TASK_POST") -> bool:
    if os.environ.get("DRY_RUN") == "1":
        print(f"[DRY RUN] LINE message would be sent:\n{message}")
        return True

    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    group_id = os.environ.get(group_id_env)
    if not token or not group_id:
        print(f"LINE secrets are not configured for {group_id_env}; skipping send.")
        return False

    payload = json.dumps({
        "to": group_id,
        "messages": [{"type": "text", "text": message}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            print(f"LINE send succeeded: HTTP {response.status}")
            return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"LINE send failed: HTTP {exc.code} - {body}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"LINE send failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    sheet_url = os.environ.get("TASKLIST_SHEET_CSV_URL")
    if not sheet_url:
        print("TASKLIST_SHEET_CSV_URL is not configured; skipping run.", file=sys.stderr)
        return 1

    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()

    try:
        csv_text = fetch_csv_text(sheet_url)
    except Exception as exc:
        print(f"Failed to download sheet: {exc}", file=sys.stderr)
        return 1

    rows = parse_sheet_rows(csv_text)
    due_tasks = extract_due_tasks(rows, today)

    if not due_tasks:
        print(f"No due tasks for {today.isoformat()}.")
        return 0

    sent_count = 0
    for task_info in due_tasks:
        message = render_line_message(task_info)
        print(f"Sending reminder for {task_info['task']}")
        if send_line_message(message, group_id_env="LINE_GROUP_ID_TASK_POST"):
            sent_count += 1

    print(f"Sent {sent_count} reminder(s) for {today.isoformat()}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
