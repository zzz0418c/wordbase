"""从笔记里读出「下次 X」这种明确写下的日期。

你的做法：每篇笔记加一页专门写日期，最后一行写「下次 10.27」。
OCR 会把 10.27 认成 1027、把 11.1 认成 111，所以这里做宽松解析。
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_MARK = re.compile(r"下\s*次?|下\s*一\s*次")


def _loose_date(raw: str, today: date) -> date | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 3:
        return None
    digits = digits[:4]

    candidates: list[tuple[int, int]] = []
    if len(digits) == 4:
        candidates.append((int(digits[:2]), int(digits[2:])))
    elif len(digits) == 3:
        candidates.append((int(digits[:2]), int(digits[2:])))
        candidates.append((int(digits[0]), int(digits[1:])))

    for month, day in candidates:
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        try:
            value = date(today.year, month, day)
        except ValueError:
            continue
        if value < today - timedelta(days=90):
            value = date(today.year + 1, month, day)
        return value
    return None


def explicit_next(text: str, today: date) -> date | None:
    """找到「下次」后面的日期；找不到返回 None。"""
    match = _MARK.search(text)
    if not match:
        return None
    tail = text[match.end(): match.end() + 16]
    return _loose_date(tail, today)


_DATE_OK = re.compile(r"(?<!\d)(\d{1,2})\s*[.。、,:：\-]\s*(\d{1,2})(?!\d)")


def all_dates(text: str, today: date) -> list[date]:
    """把一段文字里所有合理日期都抠出来（前后 120 天以内）。"""
    out: list[date] = []
    for match in _DATE_OK.finditer(text):
        month, day = int(match.group(1)), int(match.group(2))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        try:
            value = date(today.year, month, day)
        except ValueError:
            continue
        if abs((value - today).days) <= 120:
            out.append(value)
    return sorted(set(out))
