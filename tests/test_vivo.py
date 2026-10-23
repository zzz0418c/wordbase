import unittest

from vocabcurve.vivo import VivoNote, notebooks, select, to_lists


def note(nid: int, title: str, book: str = "雅思词汇", kind: int = 100, text: str = "") -> VivoNote:
    return VivoNote(id=nid, title=title, notebook=book, kind=kind, text=text)


class VivoSelectTest(unittest.TestCase):
    def setUp(self):
        self.notes = [
            note(1, "雅思词汇真经10"),
            note(2, "雅思词汇真经2"),
            note(3, "雅思词汇真经1"),
            note(4, "20261007（1）"),
            note(5, "四级unit6", book="四级"),
            note(6, ""),
        ]

    def test_notebooks_count(self):
        counts = dict(notebooks(self.notes))
        self.assertEqual(counts["雅思词汇"], 4)
        self.assertEqual(counts["四级"], 1)

    def test_pattern_and_order(self):
        picked = select(self.notes, pattern=r"^雅思词汇真经\d+$")
        self.assertEqual([n.title for n in picked], ["雅思词汇真经1", "雅思词汇真经2", "雅思词汇真经10"])

    def test_notebook_filter(self):
        picked = select(self.notes, notebook="四级")
        self.assertEqual([n.title for n in picked], ["四级unit6"])

    def test_empty_title_dropped(self):
        self.assertNotIn("", [n.title for n in select(self.notes)])


class VivoToListsTest(unittest.TestCase):
    def test_one_note_one_list(self):
        lists = to_lists([note(1, "真经01"), note(2, "真经02")])
        self.assertEqual([item.id for item in lists], ["L01", "L02"])
        self.assertEqual(lists[0].title, "真经01")

    def test_image_note_keeps_clean_words(self):
        text = "第1页\nabandon 放弃\nability 能力\nassume 假定\nnoise garbage here\n"
        lists = to_lists([note(1, "真经01", text=text)])
        self.assertEqual([w.term for w in lists[0].words], ["abandon", "ability", "assume"])

    def test_few_clean_words_treated_as_image_note(self):
        lists = to_lists([note(1, "真经01", text="abandon 放弃\nability 能力\n")])
        self.assertEqual(lists[0].words, [])


if __name__ == "__main__":
    unittest.main()
