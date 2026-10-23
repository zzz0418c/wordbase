import unittest
from datetime import date, datetime, timedelta

from vocabcurve.model import Book, Word, WordList
from vocabcurve.schedule import (
    assign_starts,
    pending_count,
    progress_rows,
    set_progress,
    due_dt,
    is_complete,
    items_on,
    mark_done,
    mark_undone,
    parse_interval,
    parse_offset,
    today_plan,
)


def make_book(start="2026-01-01", intervals=("1d", "1d", "1d"), mode="strict", lists=2, grid="relative"):
    book = Book()
    book.settings["grid"] = grid
    book.settings["intervals"] = list(intervals)
    book.settings["mode"] = mode
    book.settings["start"] = start
    book.settings["remind_at"] = "08:00"
    for index in range(lists):
        book.lists.append(
            WordList(
                id=f"L{index + 1:02d}",
                title=f"第{index + 1}篇",
                start=start,
                words=[Word("word", "释义")],
            )
        )
    return book


class IntervalTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(parse_interval("5m"), 5)
        self.assertEqual(parse_interval("30"), 30)
        self.assertEqual(parse_interval("2h"), 120)
        self.assertEqual(parse_interval("1d"), 1440)
        self.assertEqual(parse_interval("1.5h"), 90)
        self.assertEqual(parse_interval("2天"), 2880)
        self.assertEqual(parse_interval("1w"), 10080)

    def test_invalid(self):
        for bad in ("", "abc", "0m", "-1d"):
            with self.assertRaises(ValueError):
                parse_interval(bad)


class DueTest(unittest.TestCase):
    def test_strict_is_anchored(self):
        book = make_book(intervals=("1d", "2d"))
        item = book.lists[0]
        self.assertEqual(due_dt(book, item, 0), datetime(2026, 1, 1, 8, 0, tzinfo=book.tz))
        self.assertEqual(due_dt(book, item, 1), datetime(2026, 1, 2, 8, 0, tzinfo=book.tz))
        self.assertEqual(due_dt(book, item, 2), datetime(2026, 1, 4, 8, 0, tzinfo=book.tz))

    def test_adaptive_follows_actual(self):
        book = make_book(intervals=("1d", "2d"), mode="adaptive")
        item = book.lists[0]
        mark_done(book, item.id, 1, datetime(2026, 1, 5, 9, 0, tzinfo=book.tz))
        self.assertEqual(due_dt(book, item, 2), datetime(2026, 1, 7, 9, 0, tzinfo=book.tz))

    def test_strict_ignores_actual(self):
        book = make_book(intervals=("1d", "2d"))
        item = book.lists[0]
        mark_done(book, item.id, 1, datetime(2026, 1, 5, 9, 0, tzinfo=book.tz))
        self.assertEqual(due_dt(book, item, 2), datetime(2026, 1, 4, 8, 0, tzinfo=book.tz))

    def test_out_of_range(self):
        book = make_book()
        with self.assertRaises(ValueError):
            due_dt(book, book.lists[0], 4)
        with self.assertRaises(ValueError):
            due_dt(book, book.lists[0], -1)


class AssignTest(unittest.TestCase):
    def test_per_day(self):
        book = make_book()
        for item in book.lists:
            item.start = None
        assigned = assign_starts(book, date(2026, 3, 1), per_day=2)
        self.assertEqual(len(assigned), 2)
        self.assertEqual(book.lists[0].start, "2026-03-01")
        self.assertEqual(book.lists[1].start, "2026-03-01")

    def test_keeps_explicit_start(self):
        book = make_book()
        book.lists[0].start = None
        book.lists[1].start = "2026-05-05"
        assigned = assign_starts(book, date(2026, 3, 1), per_day=1)
        self.assertEqual([x.id for x in assigned], ["L01"])
        self.assertEqual(book.lists[0].start, "2026-03-01")
        self.assertEqual(book.lists[1].start, "2026-05-05")


class TodayTest(unittest.TestCase):
    def test_new_list_due(self):
        book = make_book(start="2026-01-01", intervals=("5m", "30m"), lists=1)
        plan = today_plan(book, datetime(2026, 1, 1, 8, 10, tzinfo=book.tz))
        self.assertEqual(plan["date"], "2026-01-01")
        self.assertEqual(len(plan["due_now"]), 2)  # 首学 08:00 + 第1轮 08:05
        self.assertEqual(len(plan["later"]), 1)  # 第2轮 08:35
        self.assertEqual(plan["total_overdue"], 0)

    def test_overdue_reported_once(self):
        book = make_book(start="2026-01-01", intervals=("1d", "1d", "1d"), lists=1)
        plan = today_plan(book, datetime(2026, 1, 3, 9, 0, tzinfo=book.tz))
        self.assertEqual(len(plan["overdue"]), 1)  # 只报最早积压的一轮
        self.assertEqual(plan["overdue"][0].round, 0)
        self.assertEqual(plan["total_overdue"], 1)

    def test_future_not_listed(self):
        book = make_book(start="2026-02-01", lists=1)
        plan = today_plan(book, datetime(2026, 1, 1, 9, 0, tzinfo=book.tz))
        self.assertEqual(plan["today"], [])
        self.assertEqual(plan["overdue"], [])

    def test_done_today(self):
        book = make_book(start="2026-01-01", lists=1)
        mark_done(book, "L01", 0, datetime(2026, 1, 1, 8, 20, tzinfo=book.tz))
        plan = today_plan(book, datetime(2026, 1, 1, 9, 0, tzinfo=book.tz))
        self.assertEqual(plan["done_today"][0][0], "L01")
        self.assertNotIn(0, [x.round for x in plan["due_now"]])

    def test_items_on_pending(self):
        book = make_book(intervals=("1d", "1d"), lists=1)
        items = items_on(book, date(2026, 1, 1))
        self.assertEqual(items[0].pending, 2)
        items_day2 = items_on(book, date(2026, 1, 2))
        self.assertEqual(items_day2[0].pending, 1)


class DoneTest(unittest.TestCase):
    def test_mark_and_undo(self):
        book = make_book(lists=1)
        mark_done(book, "L01", 1, datetime(2026, 1, 2, 8, 30, tzinfo=book.tz))
        self.assertIn("1", book.lists[0].done)
        mark_undone(book, "L01", 1)
        self.assertNotIn("1", book.lists[0].done)

    def test_unknown_list(self):
        book = make_book(lists=1)
        with self.assertRaises(KeyError):
            mark_done(book, "L99", 0)


class OffsetsTest(unittest.TestCase):
    """用户选的曲线：第 1/2/4/7/15/30 天，第 30 天之后算完成。"""

    def setUp(self):
        self.book = make_book(
            start="2026-03-01", intervals=("1", "2", "4", "7", "15", "30"), grid="offsets", lists=1
        )
        self.item = self.book.lists[0]

    def test_parse_offset(self):
        self.assertEqual(parse_offset("1"), 1)
        self.assertEqual(parse_offset("7d"), 7)
        self.assertEqual(parse_offset("2天"), 2)

    def test_five_reviews_on_fixed_days(self):
        # 1,2,4,7,15,30 是「第 N 天」，第 1 天是首学 -> 偏移 0,1,3,6,14,29
        self.assertEqual(self.book.rounds, 5)
        days = [0, 1, 3, 6, 14, 29]
        for round_no, offset in enumerate(days):
            expected = date(2026, 3, 1) + timedelta(days=offset)
            self.assertEqual(due_dt(self.book, self.item, round_no).date(), expected)
        self.assertEqual(due_dt(self.book, self.item, 1).time(), self.book.remind_time)

    def test_last_day_still_due(self):
        now = datetime(2026, 3, 30, 8, 0, tzinfo=self.book.tz)  # 第 30 天
        self.assertFalse(is_complete(self.book, self.item, now))
        self.assertEqual(len(items_on(self.book, now.date())), 1)

    def test_complete_after_last_day(self):
        now = datetime(2026, 4, 2, 8, 0, tzinfo=self.book.tz)  # 第 30 天之后
        self.assertTrue(is_complete(self.book, self.item, now))
        self.assertEqual(items_on(self.book, now.date()), [])
        self.assertEqual(items_on(self.book, date(2026, 4, 10)), [])
        plan = today_plan(self.book, now)
        self.assertEqual(plan["today"], [])
        self.assertEqual(len(plan["completed"]), 1)
        self.assertEqual(plan["completed"][0][0], "L01")

    def test_complete_when_all_checked(self):
        for round_no in range(self.book.rounds + 1):
            mark_done(self.book, "L01", round_no, datetime(2026, 3, 29, 7, 40, tzinfo=self.book.tz))
        now = datetime(2026, 3, 30, 8, 0, tzinfo=self.book.tz)
        self.assertTrue(is_complete(self.book, self.item, now))


class ProgressTest(unittest.TestCase):
    """从第 N 篇开始、每篇进度不同的场景。"""

    def setUp(self):
        self.book = make_book(
            start="2026-10-19", intervals=("1", "2", "4", "7", "15", "30"), grid="offsets", lists=3
        )
        self.now = datetime(2026, 10, 19, 16, 0, tzinfo=self.book.tz)

    def test_set_round_zero(self):
        set_progress(self.book, "L02", 0, self.now)
        item = self.book.lists[1]
        self.assertEqual(item.start, "2026-10-19")
        self.assertEqual(sorted(item.done), ["0"])
        self.assertEqual(due_dt(self.book, item, 1).date(), date(2026, 10, 20))

    def test_set_round_three_backdates_start(self):
        set_progress(self.book, "L02", 3, self.now)
        item = self.book.lists[1]
        # 第 3 轮对应"第 7 天"（偏移 6），所以学习日应该是 6 天前
        self.assertEqual(item.start, "2026-10-13")
        self.assertEqual(sorted(item.done), ["0", "1", "2", "3"])
        # 下一轮是第 4 轮（第 15 天，偏移 14）= 今天 + 8 天
        self.assertEqual(due_dt(self.book, item, 4).date(), date(2026, 10, 27))
        self.assertEqual(pending_count(item, self.book.rounds), 2)

    def test_set_done(self):
        set_progress(self.book, "L01", self.book.rounds, self.now)
        self.assertTrue(is_complete(self.book, self.book.lists[0], self.now))

    def test_set_not_started(self):
        set_progress(self.book, "L01", 0, self.now)
        set_progress(self.book, "L01", None, self.now)
        self.assertIsNone(self.book.lists[0].start)
        self.assertEqual(self.book.lists[0].done, {})

    def test_progress_rows(self):
        set_progress(self.book, "L01", self.book.rounds, self.now)
        set_progress(self.book, "L02", 2, self.now)
        rows = progress_rows(self.book, self.now)
        self.assertEqual(rows[0]["state"], "已完成")
        self.assertEqual(rows[1]["state"], "进行中")
        self.assertEqual(rows[1]["last_round"], 2)
        self.assertEqual(rows[2]["state"], "进行中")


if __name__ == "__main__":
    unittest.main()
