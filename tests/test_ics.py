import unittest
from datetime import datetime

from vocabcurve.ics import build_ics, escape, fold
from vocabcurve.model import Book, Word, WordList


def make_book():
    book = Book()
    book.settings["grid"] = "relative"
    book.settings["intervals"] = ["1d", "2d"]
    book.settings["start"] = "2026-01-01"
    book.settings["remind_at"] = "08:00"
    book.lists = [
        WordList(id="L01", title="第1篇 校园", start="2026-01-01", words=[Word("a", "甲")]),
        WordList(id="L02", title="第2篇 科技", start="2026-01-02", words=[Word("b", "乙")]),
    ]
    return book


class EscapeTest(unittest.TestCase):
    def test_special_chars(self):
        self.assertEqual(escape("a;b,c"), "a\\;b\\,c")
        self.assertEqual(escape("第一行\n第二行"), "第一行\\n第二行")
        self.assertEqual(escape("反斜杠\\"), "反斜杠\\\\")


class FoldTest(unittest.TestCase):
    def test_short_line(self):
        self.assertEqual(fold("SUMMARY:abc"), "SUMMARY:abc\r\n")

    def test_long_line_bytes(self):
        line = "DESCRIPTION:" + "很长的中文说明" * 20
        folded = fold(line)
        for piece in folded.split("\r\n"):
            if piece:
                self.assertLessEqual(len(piece.encode("utf-8")), 75)
        # 反折叠后应与原文一致
        self.assertEqual(folded.replace("\r\n ", "").strip(), line)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.book = make_book()
        self.now = datetime(2026, 1, 1, 8, 0, tzinfo=self.book.tz)
        self.text = build_ics(self.book, self.now, days=5, mode="detail")

    def test_envelope(self):
        self.assertTrue(self.text.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(self.text.endswith("END:VCALENDAR\r\n"))

    def test_all_lines_within_limit(self):
        for line in self.text.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75, line)

    def test_crlf_only(self):
        self.assertNotIn("\n", self.text.replace("\r\n", ""))

    def test_timezone(self):
        self.assertIn("BEGIN:VTIMEZONE", self.text)
        self.assertIn("DTSTART;TZID=Asia/Shanghai:20260101T080000", self.text)

    def test_dtstamp_is_utc(self):
        self.assertIn("DTSTAMP:20260101T000000Z", self.text)

    def test_events(self):
        # L01: 01-01 / 01-02 / 01-04，L02: 01-02 / 01-03 / 01-05，5 天窗口内共 6 条
        self.assertEqual(self.text.count("BEGIN:VEVENT"), 6)
        uids = [line for line in self.text.split("\r\n") if line.startswith("UID:")]
        self.assertEqual(len(uids), len(set(uids)))

    def test_alarm(self):
        self.assertIn("BEGIN:VALARM", self.text)
        self.assertIn("TRIGGER:-PT0M", self.text)

    def test_digest_mode(self):
        text = build_ics(self.book, self.now, days=5, mode="digest")
        # 汇总模式每天最多一条事件
        self.assertLessEqual(text.count("BEGIN:VEVENT"), 5)
        self.assertIn("单词复习", text)

    def test_escaped_newlines(self):
        for line in self.text.split("\r\n"):
            if line.startswith("DESCRIPTION:"):
                self.assertNotIn("\n", line)


if __name__ == "__main__":
    unittest.main()
