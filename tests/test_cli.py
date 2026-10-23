import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from vocabcurve.__main__ import main

SAMPLE = """第1篇 校园
abandon 放弃
ability 能力
absent 缺席的

第2篇 科技
algorithm 算法
binary 二进制的
cache 缓存
"""


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.book = self.dir / "book.json"
        self.src = self.dir / "words.txt"
        self.src.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["--book", str(self.book), *argv])
        return code, buffer.getvalue()

    def test_end_to_end(self):
        code, out = self.run_cli(
            "import", str(self.src), "--start", "2026-01-01", "--grid", "relative", "--intervals", "5m,1d"
        )
        self.assertEqual(code, 0)
        self.assertIn("2 篇", out)
        self.assertTrue(self.book.exists())

        data = json.loads(self.book.read_text(encoding="utf-8"))
        self.assertEqual(data["settings"]["intervals"], ["5m", "1d"])
        self.assertEqual(len(data["lists"]), 2)
        self.assertEqual(data["lists"][0]["start"], "2026-01-01")
        self.assertEqual(data["lists"][1]["start"], "2026-01-02")

        code, out = self.run_cli("today", "--at", "2026-01-01T08:00")
        self.assertEqual(code, 0)
        self.assertIn("首次学习", out)
        self.assertIn("L01", out)

        code, out = self.run_cli("check", "L01", "0", "--at", "2026-01-01T08:20")
        self.assertEqual(code, 0)
        self.assertIn("已打卡", out)

        code, out = self.run_cli("today", "--at", "2026-01-01T09:00", "--json")
        payload = json.loads(out)
        self.assertEqual(payload["done_today"][0][0], "L01")

        ics = self.dir / "remind.ics"
        code, _ = self.run_cli("ics", "--days", "3", "-o", str(ics))
        self.assertEqual(code, 0)
        self.assertIn("BEGIN:VCALENDAR", ics.read_text(encoding="utf-8"))

        out_dir = self.dir / "out"
        code, _ = self.run_cli("build", "--out", str(out_dir), "--days", "3", "--at", "2026-01-01T08:00")
        self.assertEqual(code, 0)
        for name in ("today.md", "today.html", "plan.md", "vocabcurve.ics"):
            self.assertTrue((out_dir / name).exists(), name)

        html = (out_dir / "today.html").read_text(encoding="utf-8")
        self.assertIn("<!doctype html>", html)
        self.assertIn("data-key=", html)

    def test_bad_intervals_rejected(self):
        code, _ = self.run_cli("import", str(self.src), "--intervals", "5m,abc")
        self.assertEqual(code, 2)
        self.assertFalse(self.book.exists())

    def test_missing_book(self):
        code, _ = self.run_cli("today")
        self.assertEqual(code, 2)

    def test_sync_progress(self):
        self.run_cli("import", str(self.src), "--start", "2026-01-01", "--grid", "relative", "--intervals", "5m,1d")
        progress = self.dir / "progress.json"
        progress.write_text(
            json.dumps({"date": "2026-01-01", "done": [{"list_id": "L01", "round": 0}]}),
            encoding="utf-8",
        )
        code, out = self.run_cli("sync", str(progress))
        self.assertEqual(code, 0)
        self.assertIn("写回 1 条", out)
        data = json.loads(self.book.read_text(encoding="utf-8"))
        self.assertIn("0", data["lists"][0]["done"])

    def test_merge_keeps_progress(self):
        self.run_cli("import", str(self.src), "--start", "2026-01-01", "--grid", "relative", "--intervals", "5m,1d")
        self.run_cli("check", "L01", "0", "--at", "2026-01-01T08:20")
        code, out = self.run_cli(
            "import", str(self.src), "--merge", "--start", "2026-01-01"
        )
        self.assertEqual(code, 0)
        self.assertIn("合并了 2 篇", out)
        data = json.loads(self.book.read_text(encoding="utf-8"))
        self.assertIn("0", data["lists"][0]["done"])
        self.assertEqual(data["settings"]["intervals"], ["5m", "1d"])  # 沿用旧曲线

    def test_brief_and_push_dry_run(self):
        self.run_cli("import", str(self.src), "--start", "2026-01-01", "--intervals", "1,2,4,7")
        code, out = self.run_cli("brief", "--at", "2026-01-01T07:40")
        self.assertEqual(code, 0)
        self.assertIn("今天", out)
        self.assertIn("第1篇", out)

        code, out = self.run_cli("push", "--dry-run", "--at", "2026-01-01T07:40")
        self.assertEqual(code, 0)
        self.assertIn("第1篇", out)

    def test_curve_printout(self):
        self.run_cli("import", str(self.src), "--start", "2026-01-01", "--grid", "relative", "--intervals", "5m,1d")
        code, out = self.run_cli("curve", "L01")
        self.assertEqual(code, 0)
        self.assertIn("首次学习", out)


if __name__ == "__main__":
    unittest.main()
