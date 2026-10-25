"""从每篇笔记第一页的 OCR 文本里，猜出这一篇复习到第几轮了。

你写的格式大概是「26.10.3 ① 10.4 ② 10.6 ③ 10.9 ④ 10.18 ⑤」——
日期 + 圈号。这里只做两件事：

1. 找日期（10.3 / 10、15 / 26.10.3 都认）；
2. 找圈号（①②③、(1)(2)），最大圈号就是已完成的最后一轮。

然后反推学习日：让第 k 轮正好落在最后一个日期上。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .model import Book

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"
_DATE_RE = re.compile(
    r"(?<!\d)(?:(?:20)?\d{2}\s*[.\-]\s*)?(\d{1,2})\s*[.。、,:：]\s*(\d{1,2})(?!\d)"
)
_YEAR_PREFIX_RE = re.compile(r"(?:20)?(2\d)\s*[.\-]\s*$")


@dataclass
class Guess:
    rounds: int | None = None  # 已完成的最后一轮；None = 没看出任何进度
    last_date: date | None = None
    next_date: date | None = None  # 手写的「下次复习」：最大圈号下面那个没圈号的日期
    start_hint: date | None = None  # 拟合出来的「第 1 天」
    confidence: int = 0  # 拟合吻合度，越高越可信
    circles: list[int] = field(default_factory=list)
    dates: list[date] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def find_circles(text: str) -> list[int]:
    found: list[int] = []
    for ch in text:
        index = CIRCLED.find(ch)
        if index >= 0:
            found.append(index + 1)
    for match in re.finditer(r"[（(]\s*(\d{1,2})\s*[)）]", text):
        value = int(match.group(1))
        if 1 <= value <= 10:
            found.append(value)
    # OCR 常把 ④ 认成数字：日期后面紧跟的单个数字也当圈号
    for match in _DATE_RE.finditer(text):
        tail = text[match.end(): match.end() + 3]
        digit = re.match(r"\s*([1-9])(?!\d)", tail)
        if digit:
            found.append(int(digit.group(1)))
    return found


def find_dates(text: str, today: date) -> list[date]:
    """只认合理区间内的日期：不在未来，也不早于 45 天前（滤掉 OCR 噪声）。"""
    dates: list[date] = []
    earliest = today - timedelta(days=45)
    for match in _DATE_RE.finditer(text):
        month, day = int(match.group(1)), int(match.group(2))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        try:
            value = date(today.year, month, day)
        except ValueError:
            continue
        if not (earliest <= value <= today):
            continue
        dates.append(value)
    return dates


def fit_start(dates: list[date], offsets: list[int], rounds: int) -> tuple[date, int]:
    """圈号已经告诉你做到第几轮了，这里只负责把「第 1 天」对齐到最吻合的日期。

    对每个候选学习日，看计划里的节点（0..rounds）有多少能对上你写的日期（允许 ±1 天）。
    """
    plan_offsets = [0] + list(offsets[:rounds])
    candidates: set[date] = set()
    for observed in dates:
        for offset in plan_offsets:
            candidates.add(observed - timedelta(days=offset))

    best: tuple[int, date] | None = None
    for start in sorted(candidates):
        planned = [start + timedelta(days=offset) for offset in plan_offsets]
        matched = sum(1 for point in planned if any(abs((point - day).days) <= 1 for day in dates))
        score = matched * 3 - (len(planned) - matched)
        if score > 0 and (best is None or score > best[0]):
            best = (score, start)
    if best is None:
        return dates[0], 0
    return best[1], best[0]


def guess(text: str, today: date, offsets: list[int] | None = None) -> Guess:
    circles = find_circles(text)
    dates = sorted(find_dates(text, today))
    result = Guess(circles=sorted(set(circles)), dates=dates)
    if not dates and not circles:
        return result

    if circles:
        # 你的写法里 ① 画在首学那天，所以圈号 n 对应第 n 个节点（0 = 首学）
        result.rounds = max(0, max(circles) - 1)
    elif dates:
        result.rounds = max(0, len(dates) - 1)  # 保守：把第一个日期当学习日

    if dates and offsets and result.rounds is not None:
        # 圈号和日期数量一致，说明「① 就画在第一个日期（首学）上」，直接采信它
        if len(result.circles) >= 2 and len(result.circles) == len(dates):
            result.start_hint, result.confidence = dates[0], 10
        else:
            result.start_hint, result.confidence = fit_start(dates, offsets, result.rounds)

    result.last_date = dates[-1] if dates else today
    result.next_date = find_next_date(text, today)
    return result


_NEXT_RE = re.compile(r"下次\s*[:：]?\s*(\d{1,2})\s*[.\-月/]\s*(\d{1,2})")


def find_next_date(text: str, today: date) -> date | None:
    """优先认「下次 10.27」这种显式写法，没有就退回"最后一个没圈号的日期"。"""
    for match in _NEXT_RE.finditer(text):
        month, day = int(match.group(1)), int(match.group(2))
        try:
            value = date(today.year, month, day)
        except ValueError:
            continue
        return value

    marks: list[tuple[date, bool]] = []
    for match in _DATE_RE.finditer(text):
        month, day = int(match.group(1)), int(match.group(2))
        try:
            value = date(today.year, month, day)
        except ValueError:
            continue
        if not (today - timedelta(days=45) <= value <= today + timedelta(days=60)):
            continue
        tail = text[match.end(): match.end() + 3].lstrip()
        circled = bool(tail) and (tail[0] in CIRCLED or tail[0] in "123456789")
        marks.append((value, circled))
    if not marks:
        return None
    last = marks[-1]
    if last[1]:
        return None
    if last[0] < today:
        return None  # "下次"应该是还没到的日子；过去的说明那是已经复习过的
    # 没圈号的那个日期必须在最后一个带圈日期之后，才是「下次」
    circled_dates = [value for value, flag in marks if flag]
    if circled_dates and last[0] <= max(circled_dates):
        return None
    return last[0]


def apply_guess(
    book: Book,
    list_id: str,
    rounds: int,
    anchor: date,
    today: date,
    next_date: date | None = None,
    start_date: date | None = None,
) -> None:
    """排这一篇。

    优先级：
    1. ``start_date``：第一页上最早那个日期，就是「第 1 天」的学习日，直接用；
    2. ``next_date``：你手写的下次复习日，让它成为下一轮；
    3. 都没有时，按曲线从上一轮推，且下一轮不早于今天。
    """
    from .schedule import due_dt, offset_days

    item = book.find(list_id)
    offsets = offset_days(book)
    rounds = max(0, min(rounds, book.rounds))

    if start_date and start_date <= anchor:
        start = start_date
    elif rounds < book.rounds and next_date and next_date >= today:
        start = next_date - timedelta(days=offsets[rounds])
    elif rounds < book.rounds:
        previous = 0 if rounds == 0 else offsets[rounds - 1]
        gap = offsets[rounds] - previous
        next_due = max(anchor + timedelta(days=gap), today)
        start = next_due - timedelta(days=offsets[rounds])
    else:
        start = anchor - timedelta(days=offsets[rounds - 1])

    item.done.clear()
    item.start = start.isoformat()
    for r in range(rounds + 1):
        item.done[str(r)] = due_dt(book, item, r).isoformat(timespec="minutes")
