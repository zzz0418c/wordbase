import unittest

from vocabcurve.parse import parse_entry, parse_text


class ParseEntryTest(unittest.TestCase):
    def test_tab(self):
        word = parse_entry("abandon\tv. 放弃；抛弃")
        assert word is not None
        self.assertEqual(word.term, "abandon")
        self.assertEqual(word.sense, "v. 放弃；抛弃")

    def test_double_space(self):
        word = parse_entry("abandon  v. 放弃")
        self.assertEqual((word.term, word.sense), ("abandon", "v. 放弃"))

    def test_single_space_cjk(self):
        word = parse_entry("abandon 放弃")
        self.assertEqual((word.term, word.sense), ("abandon", "放弃"))

    def test_dash_and_number_prefix(self):
        word = parse_entry("3. responsible - adj. 有责任的")
        self.assertEqual((word.term, word.sense), ("responsible", "adj. 有责任的"))

    def test_comments_and_separators(self):
        self.assertIsNone(parse_entry("# 第一篇"))
        self.assertIsNone(parse_entry("   "))
        self.assertIsNone(parse_entry("-----"))
        self.assertIsNone(parse_entry("// 备注"))

    def test_word_only(self):
        word = parse_entry("serendipity")
        self.assertEqual((word.term, word.sense), ("serendipity", ""))

    def test_term_with_spaces(self):
        word = parse_entry("in spite of 尽管")
        self.assertEqual((word.term, word.sense), ("in spite of", "尽管"))


class ParseTextTest(unittest.TestCase):
    TEXT = """第1篇 校园
abandon 放弃
ability 能力
absent 缺席的

第2篇 科技
algorithm 算法
binary 二进制的
cache 缓存
"""

    def test_headings(self):
        lists, report = parse_text(self.TEXT)
        self.assertEqual([item.id for item in lists], ["L01", "L02"])
        self.assertEqual(lists[0].title, "第1篇 校园")
        self.assertEqual(lists[0].size, 3)
        self.assertEqual(report.entries, 6)

    def test_unit_heading(self):
        lists, _ = parse_text("Unit 1\napple 苹果\nbanana 香蕉\ncherry 樱桃\n")
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].size, 3)

    def test_blank_line_blocks(self):
        text = "a 一个\nb 两个\nc 三个\n\nd 四个\ne 五个\nf 六个\n"
        lists, _ = parse_text(text)
        self.assertEqual(len(lists), 2)
        self.assertEqual(lists[1].words[0].term, "d")

    def test_single_block_stays_one_list(self):
        text = "a 一个\nb 两个\n"
        lists, _ = parse_text(text)
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].size, 2)

    def test_separator(self):
        text = "apple 苹果\nbanana 香蕉\n---\ncherry 樱桃\ndate 枣\n"
        lists, _ = parse_text(text)
        self.assertEqual(len(lists), 2)

    def test_preamble(self):
        text = "封面说明\n\n第1篇\napple 苹果\nbanana 香蕉\n"
        lists, _ = parse_text(text)
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].title, "第1篇")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            parse_text("\n\n   \n")

    def test_filename_title(self):
        lists, _ = parse_text("apple 苹果\nbanana 香蕉\n", title="我的单词本")
        self.assertEqual(lists[0].title, "我的单词本")


if __name__ == "__main__":
    unittest.main()
