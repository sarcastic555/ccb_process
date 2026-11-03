#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_DIR = ROOT / "automation" / "reminders"


@dataclass
class Reminder:
    kind: str
    practice_date: date
    trigger_date: date
    trigger_hour: int
    title: str
    body: str
    target: str = "メンバー全員"


def add_months(source: date, offset: int) -> date:
    year = source.year + (source.month - 1 + offset) // 12
    month = (source.month - 1 + offset) % 12 + 1
    day = min(source.day, monthrange(year, month)[1])
    return date(year, month, day)


def is_live_month(target: date) -> bool:
    anchor_year = target.year if target.month >= 10 else target.year - 1
    anchor = date(anchor_year, 10, 1)
    return target.month == add_months(anchor, 3).month and target.year == add_months(anchor, 3).year


def fourth_saturday(year: int, month: int) -> date:
    first_day = date(year, month, 1)
    # Saturday is weekday 5. Compute the first Saturday in the month while handling
    # Sunday-start months correctly, then add 21 days to reach the 4th Saturday.
    first_saturday = ((5 - first_day.weekday()) % 7) + 1
    return first_day + timedelta(days=first_saturday - 1 + 21)


def build_practice_dates(reference: date, months_ahead: int = 8) -> list[date]:
    practice_dates: list[date] = []
    month_start = date(reference.year, reference.month, 1)
    for offset in range(months_ahead + 1):
        month = add_months(month_start, offset)
        if is_live_month(month):
            continue
        practice_dates.append(fourth_saturday(month.year, month.month))
    return practice_dates


def build_reminders_for_practice(practice_date: date) -> list[Reminder]:
    studio_booking_start = add_months(practice_date, -3) + timedelta(days=1)
    attendance_start = practice_date - timedelta(days=14)
    unanswered_reminder = practice_date - timedelta(days=8)
    schedule_share = practice_date - timedelta(days=4)
    collection_sheet_print = practice_date - timedelta(days=2)
    cancellation_fee_day = practice_date - timedelta(days=6)
    rental_reminder_day = cancellation_fee_day - timedelta(days=2)

    reminders: list[Reminder] = []

    reminders.append(
        Reminder(
            kind="studio_booking_start",
            practice_date=practice_date,
            trigger_date=studio_booking_start,
            trigger_hour=9,
            title="スタジオ予約開始日",
            body="スタジオ予約が開始される日です。今週中に予約内容と会場を確認してください。",
            target="運営メンバー",
        )
    )
    reminders.append(
        Reminder(
            kind="attendance_check_start",
            practice_date=practice_date,
            trigger_date=attendance_start,
            trigger_hour=22,
            title="出欠確認開始",
            body="スタジオ練習の2週間前です。メンバーへの出欠確認を開始してください。",
            target="運営メンバー",
        )
    )
    reminders.append(
        Reminder(
            kind="attendance_followup",
            practice_date=practice_date,
            trigger_date=unanswered_reminder,
            trigger_hour=22,
            title="未回答者へのリマインド",
            body="スタジオ練習の8日前です。未回答者に出欠の再確認をお願いします。",
            target="運営メンバー",
        )
    )
    reminders.append(
        Reminder(
            kind="schedule_share",
            practice_date=practice_date,
            trigger_date=schedule_share,
            trigger_hour=22,
            title="練習タイムスケジュール共有",
            body="スタジオ練習の4日前です。練習タイムスケジュールを全体へ共有してください。",
            target="運営メンバー",
        )
    )
    reminders.append(
        Reminder(
            kind="collection_sheet_print",
            practice_date=practice_date,
            trigger_date=collection_sheet_print,
            trigger_hour=22,
            title="集金シート印刷",
            body="スタジオ練習の2日前です。集金シートを印刷して準備してください。",
            target="運営メンバー",
        )
    )
    reminders.append(
        Reminder(
            kind="cancellation_fee_warning",
            practice_date=practice_date,
            trigger_date=rental_reminder_day,
            trigger_hour=22,
            title="キャンセル料発生前の確認",
            body="キャンセル料発生まで2日前です。予約状況とキャンセル判断を再確認してください。",
            target="運営メンバー",
        )
    )
    reminders.append(
        Reminder(
            kind="rental_item_notice",
            practice_date=practice_date,
            trigger_date=rental_reminder_day,
            trigger_hour=22,
            title="レンタル品の連絡",
            body="スタジオへのレンタル品連絡を忘れないようにしてください。確認が必要な場合は早めに連絡をお願いします。",
            target="運営メンバー",
        )
    )
    return reminders


def load_sent_history(history_path: Path) -> dict[str, str]:
    if not history_path.exists():
        return {}
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_sent_history(history_path: Path, state: dict[str, str]) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def send_line_message(message: str) -> bool:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    group_id = os.environ.get("LINE_GROUP_ID_PERSONAL")
    if not token or not group_id:
        print("LINE secret is not configured; skipping actual send.")
        return False

    payload = json.dumps({
        "to": group_id,
        "messages": [{"type": "text", "text": message}],
    }).encode("utf-8")

    req = request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=30) as res:
            print(f"LINE send succeeded: HTTP {res.status}")
            return True
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"LINE send failed: HTTP {exc.code} - {body}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"LINE send failed: {exc}", file=sys.stderr)
        return False


def render_markdown(reminders: list[Reminder], today: date) -> str:
    lines = [
        "# Conditioned Reminder Report",
        "",
        f"- 評価日: {today.isoformat()}",
        "",
    ]
    if not reminders:
        lines.append("- 条件に合致するリマインドはありません。")
        return "\n".join(lines) + "\n"

    for reminder in reminders:
        lines.extend([
            f"## {reminder.title}",
            f"- 種別: {reminder.kind}",
            f"- 実施予定日: {reminder.practice_date.isoformat()}",
            f"- 判定日: {reminder.trigger_date.isoformat()}",
            f"- 発火時刻: {reminder.trigger_hour}:00",
            f"- 対象: {reminder.target}",
            f"- 本文: {reminder.body}",
            "",
        ])
    return "\n".join(lines) + "\n"


def main() -> int:
    AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()
    history_path = AUTOMATION_DIR / "sent_history.json"
    sent_history = load_sent_history(history_path)

    due_reminders: list[Reminder] = []
    current_hour = datetime.now().hour
    for practice_date in build_practice_dates(today, months_ahead=8):
        for reminder in build_reminders_for_practice(practice_date):
            if reminder.trigger_date == today and reminder.trigger_hour == current_hour:
                due_reminders.append(reminder)

    report_path = AUTOMATION_DIR / f"reminder_{today.isoformat()}.md"
    if due_reminders:
        missing_line_config = []
        for reminder in due_reminders:
            key = f"{reminder.kind}:{reminder.trigger_date.isoformat()}:{reminder.trigger_hour}"
            if key in sent_history:
                print(f"Skipping already sent reminder: {key}")
                continue

            message = (
                f"[{reminder.title}]\n"
                f"実施予定日: {reminder.practice_date.isoformat()}\n"
                f"{reminder.body}"
            )
            token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
            group_id = os.environ.get("LINE_GROUP_ID_PERSONAL")
            if not token or not group_id:
                missing_line_config.append(key)
                print(f"Reminder not sent due to unavailable LINE configuration: {key}")
                continue

            sent = send_line_message(message)
            if sent:
                sent_history[key] = datetime.now().isoformat(timespec="seconds")

        report_path.write_text(render_markdown(due_reminders, today), encoding="utf-8")
        save_sent_history(history_path, sent_history)
        print(f"Reminder report written: {report_path}")

        if missing_line_config:
            print("ERROR: LINE configuration is missing; failing workflow intentionally.", file=sys.stderr)
            raise SystemExit(1)

        return 0

    pending_path = AUTOMATION_DIR / f"reminder_{today.isoformat()}_pending.md"
    pending_path.write_text(
        "# Conditioned Reminder Report\n\n- 今日発火するリマインドはありません。\n",
        encoding="utf-8",
    )
    print(f"No reminder due today; wrote pending report: {pending_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
