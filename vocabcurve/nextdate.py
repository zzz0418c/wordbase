"""从笔记的「日期页」里读出下次复习日。

你的日期页是手写拍照的，OCR 会把 `10.27` 认成 `1027`、把两个日期黏成 `10.1910.22`。
所以这里不做正则硬匹配，而是逐字符扫描 `数字 + 分隔符 + 数字`，允许重叠，
再把所有候选日期取最大值 —— 日期页上的日期是从早到晚写的，最后一个就是「下次」。
"""

from __future__ import annotations

import re
from datetime import date

_MARK = re.compile(r"下\s*次|下\s*一\s*次")
_SEP = ".。,，、:：-"


def scan_dates(text: str, today: date) -> list[date]:
    """逐位置扫描，抓出所有像日期的东西（前后 120 天内）。"""
    found: set[date] = set()
    length = len(text)
    for i in range(length):
        if not (text[i].isascii() and text[i].isdigit()):
            continue
        for width in (1, 2):
            if i + width > length:
                continue
            head = text[i:i + width]
            if not (head.isascii() and head.isdigit()):
                continue
            pos = i + width
            if pos < length and text[pos] in _SEP:
                pos += 1
                for d_width in (1, 2):
                    tail = text[pos:pos + d_width]
                    if len(tail) == d_width and tail.isascii() and tail.isdigit():
                        month, day = int(head), int(tail)
                        if 1 <= month <= 12 and 1 <= day <= 31:
                            try:
                                value = date(today.year, month, day)
                            except ValueError:
                                continue
                            if abs((value - today).days) <= 120:
                                found.add(value)
    return sorted(found)


def _loose_next_after_mark(text: str, today: date) -> date | None:
    matches = list(_MARK.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    tail = text[match.end(): match.end() + 18]
    dates = scan_dates(tail, today)
    if dates:
        return dates[-1]

    # OCR 会把 "11.1" 认成 "111"，没有分隔符，这里兜一次底
    digits = re.sub(r"\D", "", tail)[:4]
    if len(digits) in (3, 4):
        month, day = int(digits[:2]), int(digits[2:])
        if not (1 <= month <= 12 and 1 <= day <= 31):
            month, day = int(digits[0]), int(digits[1:])
        if 1 <= month <= 12 and 1 <= day <= 31:
            try:
                return date(today.year, month, day)
            except ValueError:
                return None
    return None


def best_page_next(pages: list[str], today: date) -> tuple[date | None, int, str]:
    """在笔记的所有页里挑最像「日期页」的那一页，返回 (下次日期, 页号, 依据)。"""
    best: tuple[int, int, str, list[date]] | None = None
    for index, page in enumerate(pages):
        dates = scan_dates(page, today)
        if len(dates) < 2:
            continue
        # 日期页一定是短页；长页是单词正文，里面的数字只是噪声
        if len(page) > 120:
            continue
        score = len(dates) * 3 - (len(page) // 40)
        if best is None or score > best[0]:
            best = (score, index, page, dates)

    if best is None:
        return None, -1, ""

    _, index, page, dates = best
    explicit = _loose_next_after_mark(page, today)
    if explicit:
        return explicit, index, f"下次标记 {explicit:%m-%d}"
    return dates[-1], index, f"页内最大日期 {dates[-1]:%m-%d}"


def parse_loose(raw: str, today: date) -> date | None:
    """把「1027」「111」这种粘连数字解析成日期。"""
    digits = re.sub(r"\D", "", raw)[:4]
    if len(digits) not in (3, 4):
        return None
    for month, day in ((int(digits[:2]), int(digits[2:])), (int(digits[0]), int(digits[1:]))):
        if 1 <= month <= 12 and 1 <= day <= 31:
            try:
                return date(today.year, month, day)
            except ValueError:
                continue
    return None
