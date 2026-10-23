"""记忆曲线排程：间隔解析、日期推算、今日任务、逾期处理。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable

from .model import Book, WordList, parse_day

# ---------------------------------------------------------------- 间隔解析

_UNIT_MINUTES = {
    "m": 1, "min": 1, "mins": 1, "分钟": 1, "分": 1,
    "h": 60, "hr": 60, "hour": 60, "hours": 60, "小时": 60, "时": 60,
    "d": 1440, "day": 1440, "days": 1440, "天": 1440, "日": 1440,
    "w": 10080, "week": 10080, "weeks": 10080, "周": 10080, "星期": 10080,
}

_INTERVAL_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(分钟|分|min|mins|m|小时|时|hr|h|天|日|day|days|d|周|星期|week|weeks|w)?\s*$",
    re.IGNORECASE,
)


def parse_interval(text: str) -> int:
    """'30m' / '12h' / '1d' / '2天' / '45' -> 分钟数（纯数字按分钟）。"""
    match = _INTERVAL_RE.match(str(text))
    if not match:
        raise ValueError(f"看不懂的间隔 {text!r}，请用 30m / 12h / 1d / 2w 这样的写法")
    value = float(match.group(1))
    unit = (match.group(2) or "m").lower()
    if unit not in _UNIT_MINUTES:
        raise ValueError(f"不支持的间隔单位 {unit!r}")
    minutes = int(round(value * _UNIT_MINUTES[unit]))
    if minutes <= 0:
        raise ValueError(f"间隔必须大于 0：{text!r}")
    return minutes


def parse_intervals(items: Iterable[str]) -> list[int]:
    return [parse_interval(item) for item in items]


_OFFSET_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(天|日|d|day|days|周|w|week|weeks)?\s*$", re.IGNORECASE)


def parse_offset(text: str) -> int:
    """'1' / '1d' / '2天' / '1w' -> 距学习日的天数（offsets 网格用）。"""
    match = _OFFSET_RE.match(str(text))
    if not match:
        raise ValueError(f"看不懂的复习节点 {text!r}，offsets 模式请写 1 / 2 / 4 / 7 / 15 / 30")
    value = float(match.group(1))
    unit = (match.group(2) or "d").lower()
    days = value * (7 if unit in {"w", "week", "weeks", "周"} else 1)
    days = int(round(days))
    if days <= 0:
        raise ValueError(f"节点必须大于 0 天：{text!r}")
    return days


def is_offsets(book: Book) -> bool:
    return str(book.settings.get("grid") or "offsets").lower() == "offsets"


def offset_days(book: Book) -> list[int]:
    """intervals 写的是「第 N 天」（首学 = 第 1 天），换算成相对首学的天数偏移。

    1,2,4,7,15,30  ->  1,3,6,14,29   （第 1 天是首学本身，不算复习）
    """
    days = [parse_offset(x) for x in book.settings.get("intervals") or []]
    base = int(book.settings.get("day_base") or 1)
    offsets = [day - base for day in days]
    if offsets and offsets[0] == 0:
        offsets = offsets[1:]
    if not offsets:
        raise ValueError("曲线里除首学外至少要有一个复习节点")
    return offsets


def humanize(minutes: int) -> str:
    """分钟数 -> '15m' / '12h' / '3d' 这类紧凑写法。"""
    if minutes % 10080 == 0:
        return f"{minutes // 10080}w"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def humanize_span(minutes: int) -> str:
    """跨度写法：'59 天 12 小时'，用在「整条曲线多久走完」这种地方。"""
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    parts = []
    if days:
        parts.append(f"{days} 天")
    if hours:
        parts.append(f"{hours} 小时")
    if mins or not parts:
        parts.append(f"{mins} 分钟")
    return " ".join(parts)


def describe_curve(book: Book) -> str:
    if is_offsets(book):
        numbers = [parse_offset(x) for x in book.settings.get("intervals") or []]
        reviews = max(0, len(numbers) - 1)
        return (
            "第 " + " / ".join(str(n) for n in numbers) + " 天"
            + f"（首学 = 第 1 天，共 {reviews} 次复习，第 {numbers[-1]} 天后完成）"
        )
    mins = parse_intervals(book.settings.get("intervals") or [])
    parts = [humanize(m) for m in mins]
    total = sum(mins)
    return " → ".join(parts) + f"（{len(mins)} 个节点，走完约需 {humanize_span(total)}）"


# ---------------------------------------------------------------- 时间推算


def study_dt(book: Book, item: WordList) -> datetime:
    """该篇「首次学习」的计划时刻。"""
    if not item.start:
        raise ValueError(f"{item.id} 还没有 start 日期")
    day = parse_day(item.start)
    return datetime.combine(day, book.remind_time, tzinfo=book.tz)


def due_dt(book: Book, item: WordList, round_no: int) -> datetime:
    """第 ``round_no`` 轮（0 = 首次学习）的计划时刻。

    offsets 网格（默认）：第 1/2/4/7/15/30 天各复习一次，全部锚定学习日；
    relative 网格：节点是「距上一次多久」，5m/30m/12h 这类当天多轮用它。
    adaptive 模式会把上一轮的实际延误加到本轮上。
    """
    if round_no < 0 or round_no > book.rounds:
        raise ValueError(f"轮次 {round_no} 超出范围 0..{book.rounds}")
    base = study_dt(book, item)
    if round_no == 0:
        return base

    if is_offsets(book):
        days = offset_days(book)
        planned = base + timedelta(days=days[round_no - 1])
        if book.mode == "adaptive" and round_no >= 2:
            previous_planned = base + timedelta(days=days[round_no - 2])
            actual = item.done.get(str(round_no - 1))
            if actual:
                planned += datetime.fromisoformat(actual) - previous_planned
        return planned

    minutes = parse_intervals(book.settings.get("intervals") or [])
    if book.mode != "adaptive":
        return base + timedelta(minutes=sum(minutes[:round_no]))

    cursor = base
    for step in range(1, round_no):
        actual = item.done.get(str(step))
        if actual:
            cursor = datetime.fromisoformat(actual)
        else:
            cursor = cursor + timedelta(minutes=minutes[step - 1])
    return cursor + timedelta(minutes=minutes[round_no - 1])


def next_pending(item: WordList, rounds: int) -> int | None:
    for r in range(rounds + 1):
        if str(r) not in item.done:
            return r
    return None


def pending_count(item: WordList, rounds: int) -> int:
    return sum(1 for r in range(rounds + 1) if str(r) not in item.done)


def completed_on(book: Book, item: WordList, now: datetime | None = None) -> date | None:
    """这一篇什么时候算「完成」：打完全部卡，或者最后一个节点已经过去。

    返回完成日期；还没完成返回 None。
    """
    now = now or datetime.now(book.tz)
    if item.finished(book.rounds):
        stamps = []
        for stamp in item.done.values():
            try:
                stamps.append(datetime.fromisoformat(stamp).date())
            except ValueError:
                continue
        return max(stamps) if stamps else now.date()

    last = due_dt(book, item, book.rounds)
    if now.date() > last.date():
        return last.date()
    return None


def is_complete(book: Book, item: WordList, now: datetime | None = None) -> bool:
    return completed_on(book, item, now) is not None


def missing_rounds(book: Book, item: WordList) -> int:
    return pending_count(item, book.rounds)


# ---------------------------------------------------------------- 排期


def assign_starts(book: Book, start: date, per_day: int = 1, order: list[str] | None = None) -> list[WordList]:
    """给还没有 start 的篇目按顺序铺日期：每天 ``per_day`` 篇。

    ``order`` 是篇号顺序（比如先 16-22 再 1-15）；没给的篇排在后面补齐。
    """
    per_day = max(1, int(per_day))
    cursor = start
    assigned: list[WordList] = []
    slot = 0

    by_id = {item.id: item for item in book.lists}
    sequence: list[WordList] = []
    if order:
        sequence = [by_id[list_id] for list_id in order if list_id in by_id]
    seen = {id(item) for item in sequence}
    sequence += [item for item in book.lists if id(item) not in seen]

    for item in sequence:
        if item.start:
            continue
        item.start = cursor.isoformat()
        assigned.append(item)
        slot += 1
        if slot >= per_day:
            slot = 0
            cursor = cursor + timedelta(days=1)
    return assigned


# ---------------------------------------------------------------- 今日任务


@dataclass
class Item:
    list_id: str
    title: str
    round: int
    due: datetime
    status: str  # new | due | later | overdue
    pending: int = 0  # 做完这一轮之后，本篇还剩下的轮数

    @property
    def label(self) -> str:
        return "首次学习" if self.round == 0 else f"第 {self.round} 轮"


def _mk(book: Book, item: WordList, round_no: int, status: str) -> Item:
    return Item(
        list_id=item.id,
        title=item.title,
        round=round_no,
        due=due_dt(book, item, round_no),
        status=status,
        pending=max(0, book.rounds - round_no),
    )


def items_on(book: Book, day: date) -> list[Item]:
    """某一天计划要做的全部任务（不含已打卡、不含已完成/已过期的篇）。"""
    out: list[Item] = []
    for item in book.lists:
        if item.finished(book.rounds):
            continue
        last_day = due_dt(book, item, book.rounds).date()
        if day > last_day:
            continue  # 最后一个节点都过去了，这一篇不再产生任何提醒
        for r in range(book.rounds + 1):
            if str(r) in item.done:
                continue
            due = due_dt(book, item, r)
            if due.date() == day:
                out.append(
                    Item(
                        item.id,
                        item.title,
                        r,
                        due,
                        "new" if r == 0 else "due",
                        pending=max(0, book.rounds - r),
                    )
                )
    out.sort(key=lambda x: (x.due, x.list_id))
    return out


def today_plan(book: Book, now: datetime | None = None) -> dict:
    """今日看板：今天该做的 + 积压的（每篇只报最该补的那一轮）+ 已完成的。"""
    now = now or datetime.now(book.tz)
    today = now.date()

    done_today: list[tuple[str, int, str]] = []
    completed: list[tuple[str, str, date, int]] = []
    todays: list[Item] = []
    overdue: list[Item] = []
    later: list[Item] = []

    for item in book.lists:
        for r, stamp in item.done.items():
            try:
                if datetime.fromisoformat(stamp).date() == today:
                    done_today.append((item.id, int(r), stamp))
            except ValueError:
                continue

        done_on = completed_on(book, item, now)
        if done_on is not None:
            completed.append((item.id, item.title, done_on, missing_rounds(book, item)))
            continue

        for r in range(book.rounds + 1):
            if str(r) in item.done:
                continue
            due = due_dt(book, item, r)
            if due.date() < today:
                overdue.append(_mk(book, item, r, "overdue"))
                break  # 每篇只报最早积压的一轮，避免刷屏
            if due.date() == today:
                if due > now:
                    later.append(_mk(book, item, r, "later"))
                else:
                    todays.append(_mk(book, item, r, "due"))

    todays.sort(key=lambda x: (x.due, x.list_id))
    overdue.sort(key=lambda x: (x.due, x.list_id))
    later.sort(key=lambda x: (x.due, x.list_id))
    completed.sort(key=lambda x: x[0])

    # 已经走完曲线的篇不再重复出现在「今天已完成」里，避免刷屏
    finished_ids = {row[0] for row in completed}
    done_today = [entry for entry in done_today if entry[0] not in finished_ids]

    return {
        "date": today.isoformat(),
        "now": now.isoformat(timespec="minutes"),
        # 已到点 + 今天稍后，按时间排
        "today": todays + later,
        "due_now": todays,
        "later": later,
        "overdue": overdue,
        "completed": completed,
        "done_today": sorted(done_today, key=lambda x: x[1]),
        "total_due": len(todays) + len(later),
        "total_overdue": len(overdue),
    }


def set_progress(book: Book, list_id: str, last_round: int | None, now: datetime) -> WordList:
    """把某一篇的进度直接"摆"到指定位置。

    ``last_round`` 是**已经完成的最后一轮**（0 = 只学完首学，None = 还没开始）。
    做法是反推学习日：让第 ``last_round`` 个节点正好落在今天，这样剩下的节点
    自然就按 1/2/4/7/15/30 排下去，历史打卡也补成计划时刻。
    """
    if not is_offsets(book):
        raise ValueError("progress 只支持 offsets 网格（第 N 天复习）")
    item = book.find(list_id)
    item.done.clear()

    if last_round is None:
        item.start = None
        return item

    last_round = max(0, min(int(last_round), book.rounds))
    offsets = offset_days(book)
    offset = 0 if last_round == 0 else offsets[last_round - 1]
    start = now.date() - timedelta(days=offset)
    item.start = start.isoformat()
    for r in range(last_round + 1):
        item.done[str(r)] = due_dt(book, item, r).isoformat(timespec="minutes")
    return item


def progress_rows(book: Book, now: datetime | None = None) -> list[dict]:
    """每篇一行，给 CLI 表格用。"""
    now = now or datetime.now(book.tz)
    rows = []
    for item in book.lists:
        done_on = completed_on(book, item, now)
        if done_on is not None:
            state = "已完成"
            last = book.rounds
            next_due = None
        elif not item.start:
            state = "未开始"
            last = -1
            next_due = None
        elif not item.done and parse_day(item.start) > now.date():
            state = "未开始"
            last = -1
            next_due = due_dt(book, item, 0)
        else:
            done_rounds = [int(k) for k in item.done if k.isdigit()]
            last = max(done_rounds) if done_rounds else -1
            state = "进行中"
            nxt = next_pending(item, book.rounds)
            next_due = due_dt(book, item, nxt) if nxt is not None else None
        rows.append(
            {
                "id": item.id,
                "title": item.title,
                "state": state,
                "last_round": last,
                "next_due": next_due,
                "remaining": pending_count(item, book.rounds),
            }
        )
    return rows


def upcoming(book: Book, now: datetime | None = None, days: int = 30) -> list[tuple[date, list[Item]]]:
    now = now or datetime.now(book.tz)
    out: list[tuple[date, list[Item]]] = []
    for offset in range(days):
        day = now.date() + timedelta(days=offset)
        out.append((day, items_on(book, day)))
    return out


def workload(book: Book, now: datetime | None = None, days: int = 30) -> dict[date, int]:
    return {day: len(items) for day, items in upcoming(book, now, days)}


def mark_done(book: Book, list_id: str, round_no: int, when: datetime | None = None) -> WordList:
    item = book.find(list_id)
    if round_no < 0 or round_no > book.rounds:
        raise ValueError(f"轮次 {round_no} 超出范围 0..{book.rounds}")
    when = when or datetime.now(book.tz)
    item.done[str(round_no)] = when.isoformat(timespec="minutes")
    return item


def mark_undone(book: Book, list_id: str, round_no: int) -> WordList:
    item = book.find(list_id)
    item.done.pop(str(round_no), None)
    return item


def curve_for(book: Book, item: WordList) -> list[tuple[int, datetime, str | None]]:
    """一篇的完整时间表：[(轮次, 计划时刻, 实际打卡时间或 None)]。"""
    return [
        (r, due_dt(book, item, r), item.done.get(str(r)))
        for r in range(book.rounds + 1)
    ]
