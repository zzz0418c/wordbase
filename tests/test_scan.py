import unittest
from datetime import date

from vocabcurve.scan import find_circles, find_dates, guess


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 10, 19)

    def test_circles(self):
        self.assertEqual(find_circles("26.10.3 ① 10.4 ② 10.6 ③"), [1, 2, 3])
        self.assertEqual(find_circles("10.12 (4) 10.18（5）"), [4, 5])

    def test_dates_filter_noise(self):
        text = "26.10.17 10.18 12.17 1.1 10.23"
        found = find_dates(text, self.today)
        # 12.17 / 1.1 太旧，10.23 在未来，都应被过滤
        self.assertEqual(found, [date(2026, 10, 17), date(2026, 10, 18)])

    def test_guess_uses_max_circle(self):
        result = guess("26.10.3 ① 10.4 ② 10.6 ③ 10.18 ④", self.today)
        self.assertEqual(result.rounds, 3)
        self.assertEqual(result.last_date, date(2026, 10, 18))

    def test_guess_without_circle_counts_dates(self):
        result = guess("10.17 10.18", self.today)
        self.assertEqual(result.rounds, 1)
        self.assertEqual(result.last_date, date(2026, 10, 18))

    def test_guess_empty(self):
        result = guess("biologist mammal primate", self.today)
        self.assertIsNone(result.rounds)


if __name__ == "__main__":
    unittest.main()
