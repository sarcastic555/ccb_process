import unittest
from datetime import date

from scripts.tasklist_daily_reminder import extract_due_tasks, parse_date, parse_sheet_rows


class TasklistDailyReminderTests(unittest.TestCase):
    def test_parse_date(self):
        self.assertEqual(parse_date("2026/10/24"), date(2026, 10, 24))
        self.assertEqual(parse_date("2026-10-24"), date(2026, 10, 24))
        self.assertEqual(parse_date("2026年10月24日"), date(2026, 10, 24))

    def test_extract_due_tasks_filters_by_today(self):
        rows = [
            {
                "実施日": "2026/10/24",
                "タスク": "進捗確認",
                "担当": "代表",
                "大分類": "運営",
            },
            {
                "実施日": "2026/10/25",
                "タスク": "別件",
                "担当": "広報",
                "大分類": "宣伝",
            },
            {
                "実施日": "2026/10/24",
                "タスク": "",
                "担当": "",
                "大分類": "",
            },
        ]

        due = extract_due_tasks(rows, date(2026, 10, 24))

        self.assertEqual(
            due,
            [
                {
                    "task": "進捗確認",
                    "assignee": "代表",
                    "category": "運営",
                    "date": date(2026, 10, 24),
                }
            ],
        )

    def test_parse_sheet_rows_handles_duplicate_date_columns(self):
        csv_text = (
            "大分類,小分類,タスク,担当,実施日,実施日\n"
            "運営,計画,再確認,代表,全体練習1回目の120日前,2026/11/03\n"
        )

        rows = parse_sheet_rows(csv_text)

        self.assertEqual(rows[0]["実施日"], "2026/11/03")
        self.assertEqual(
            extract_due_tasks(rows, date(2026, 11, 3)),
            [
                {
                    "task": "再確認",
                    "assignee": "代表",
                    "category": "運営",
                    "date": date(2026, 11, 3),
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
