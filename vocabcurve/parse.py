"""把「原子笔记」里抄出来的单词本，切成一篇篇、一行行。

支持：.txt / .md / .csv / .xlsx / .docx，或者直接把文字粘进 stdin。
解析策略是「尽量认得出，但绝不瞎猜」：认不出的行会原样保留成
term 只有单词、没有释义的条目，并计入警告，方便你回头修。
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from .model import Word, WordList

#: 「第 1 篇 / Unit 3 / List 5 / Lesson 2 / Day 7」这类篇目标题
HEADER_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(?:"
    r"第\s*[0-9０-９一二三四五六七八九十百零两]+\s*[篇单元课组章节]"
    r"|(?:unit|list|lesson|day|part|chapter|set|section)\s*[0-9]+"
    r"|第\s*[0-9０-９]+\s*[天周]"
    r")"
    r"\s*[:：.、\-—]?\s*(.*)$",
    re.IGNORECASE,
)

SEPARATOR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|={3,}|＿{3,})\s*$")
COMMENT_RE = re.compile(r"^\s*(?:#|//|;;)")
NUMBER_PREFIX_RE = re.compile(r"^\s*[（(]?\d{1,3}[)）.、．:：]\s*")

_DELIMS = ("\t", "  ", " – ", " — ", " - ", "：", ":", "；", ";", "，", ",", "、")
#: 「abandon 放弃」这种英文 + 中文单空格
_ASCII_CJK_RE = re.compile(r"^([A-Za-z][A-Za-z'’\-\.\* /]*?)\s+([\u3400-\u9fff].*)$")


@dataclass
class Report:
    sections: int = 0
    entries: int = 0
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        if len(self.warnings) < 20:
            self.warnings.append(message)


def parse_entry(line: str) -> Word | None:
    """一行 -> Word；空行/注释/分隔线返回 None。"""
    raw = line.strip()
    if not raw or SEPARATOR_RE.match(raw) or COMMENT_RE.match(raw):
        return None
    text = NUMBER_PREFIX_RE.sub("", raw, count=1).strip()
    if not text:
        return None

    for delim in _DELIMS:
        if delim in text:
            term, _, sense = text.partition(delim)
            term, sense = term.strip(), sense.strip()
            if term and sense:
                return Word(term, sense)
            break  # 分隔符在开头（比如中文释义里带逗号）就退回整体判断

    match = _ASCII_CJK_RE.match(text)
    if match:
        return Word(match.group(1).strip(), match.group(2).strip())

    return Word(text, "")


def split_sections(text: str, report: Report | None = None) -> list[tuple[str | None, list[str]]]:
    """按篇目标题 / 分隔线 / 空行块切段。返回 [(标题或 None, 原始行列表)]。"""
    report = report or Report()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    has_header = any(HEADER_RE.match(line) for line in lines)
    if has_header:
        sections: list[tuple[str, list[str]]] = []
        current: tuple[str, list[str]] | None = None
        preamble: list[str] = []
        for line in lines:
            if HEADER_RE.match(line):
                current = (line.strip().lstrip("#").strip(), [])
                sections.append(current)
            elif current is not None:
                current[1].append(line)
            elif line.strip():
                preamble.append(line)
        # 标题前的内容多半是书名/日期/备注，只有像样成篇（>= 3 个词条）才收养
        preamble_words = [word for word in map(parse_entry, preamble) if word]
        if len(preamble_words) >= 3:
            sections.insert(0, ("开篇", preamble))
        return sections

    if any(SEPARATOR_RE.match(line) for line in lines):
        blocks: list[list[str]] = [[]]
        for line in lines:
            if SEPARATOR_RE.match(line):
                blocks.append([])
            else:
                blocks[-1].append(line)
        return [(None, block) for block in blocks]

    blocks = re.split(r"\n\s*\n", text.strip()) if text.strip() else []
    chunks = [block.split("\n") for block in blocks if block.strip()]
    # 只有在「每块都像一篇（>= 3 行）」时才按空行切，避免两三个单词被拆成一堆篇
    if len(chunks) >= 2 and all(len([ln for ln in c if ln.strip()]) >= 3 for c in chunks):
        return [(None, chunk) for chunk in chunks]
    return [(None, text.split("\n"))]


def parse_entry_has_no_delim(line: str) -> bool:
    """保留给外部调用：判断这行是否可能是纯标题。"""
    return "\t" not in line and "  " not in line.strip()


def parse_text(text: str, title: str | None = None) -> tuple[list[WordList], Report]:
    report = Report()
    sections = split_sections(text, report)
    lists: list[WordList] = []

    for index, (heading, raw_lines) in enumerate(sections, start=1):
        words: list[Word] = []
        for line in raw_lines:
            word = parse_entry(line)
            if word is None:
                continue
            if not word.sense and len(line.strip().split()) > 3:
                report.warn(f"这一行没认出释义：{line.strip()[:40]}")
            words.append(word)
        if not words:
            continue
        name = heading or f"第{len(lists) + 1}篇"
        if title and len(sections) == 1:
            name = title
        lists.append(WordList(id=f"L{len(lists) + 1:02d}", title=name, words=words))
        report.entries += len(words)

    if not lists:
        raise ValueError("没有解析出任何单词，检查一下文件里是不是只有标题/空行")

    report.sections = len(lists)
    return lists, report


# ---------------------------------------------------------------- 文件读取


def read_docx(path: Path) -> str:
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("读 .docx 需要 python-docx：pip install python-docx") from exc

    document = Document(str(path))
    lines = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            cells = [cell for cell in cells if cell]
            if cells:
                lines.append("\t".join(cells[:2]))
    return "\n".join(lines)


def read_xlsx(path: Path) -> str:
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("读 .xlsx 需要 openpyxl：pip install openpyxl") from exc

    workbook = load_workbook(str(path), read_only=True, data_only=True)
    lines: list[str] = []
    for sheet in workbook.worksheets:
        lines.append(f"第{sheet.title}篇" if sheet.title else "第1篇")
        for row in sheet.iter_rows(values_only=True):
            cells = [str(cell).strip() for cell in row if cell not in (None, "")]
            if cells:
                lines.append("\t".join(cells[:2]))
    return "\n".join(lines)


def read_csv_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        rows = list(csv.reader(io.StringIO(raw)))
    except csv.Error:
        return raw
    lines: list[str] = []
    for row in rows:
        cells = [cell.strip() for cell in row if cell and cell.strip()]
        if not cells:
            continue
        if cells[0].lower() in {"word", "term", "单词", "英文"}:
            continue
        lines.append("\t".join(cells[:2]))
    return "\n".join(lines)


def load_source(source: str | Path) -> tuple[list[WordList], Report]:
    """路径或原始文本 -> 篇列表。"""
    path = Path(source)
    if path.exists() and path.is_file():
        suffix = path.suffix.lower()
        if suffix == ".docx":
            text = read_docx(path)
        elif suffix == ".xlsx":
            text = read_xlsx(path)
        elif suffix == ".csv":
            text = read_csv_text(path)
        else:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        return parse_text(text, title=path.stem)

    text = str(source)
    if not text.strip():
        raise ValueError("输入是空的")
    return parse_text(text, title=None)


def guess_start_hint(lists: list[WordList]) -> str:
    sizes = [item.size for item in lists]
    return f"{len(lists)} 篇 / {sum(sizes)} 词（每篇 {min(sizes)}–{max(sizes)} 词）"
