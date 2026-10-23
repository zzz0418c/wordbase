"""导出 .ics 日历：丢进平板自带的日历里，就有原生提醒了，不用装 App、不用后台服务。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .model import Book
from .schedule import Item, items_on, today_plan

CHINA_TZ = "Asia/Shanghai"


def escape(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """RFC 5545：每行不超过 75 个八位组，续行以空格开头。"""
    data = line.encode("utf-8")
    if len(data) <= 75:
        return line + "\r\n"
    chunks: list[str] = []
    first = True
    while data:
        limit = 75 if first else 74
        chunk = data[:limit]
        while chunk:
            try:
                text = chunk.decode("utf-8")
                break
            except UnicodeDecodeError:
                chunk = chunk[:-1]
        else:  # pragma: no cover - 不会发生
            break
        chunks.append(("" if first else " ") + text)
        data = data[len(chunk):]
        first = False
    return "\r\n".join(chunks) + "\r\n"


def _dt(value: datetime, tzid: str | None) -> str:
    stamp = value.strftime("%Y%m%dT%H%M%S")
    return f";TZID={tzid}:{stamp}" if tzid else f":{stamp}"


def _vtimezone(tzid: str) -> list[str]:
    if tzid != CHINA_TZ:
        return []  # 其他时区用浮动时间，跟随设备本地时区
    return [
        "BEGIN:VTIMEZONE",
        f"TZID:{tzid}",
        f"X-LIC-LOCATION:{tzid}",
        "BEGIN:STANDARD",
        "TZOFFSETFROM:+0800",
        "TZOFFSETTO:+0800",
        "TZNAME:CST",
        "DTSTART:19700101T000000",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]


def _event(
    *,
    uid: str,
    start: datetime,
    minutes: int,
    summary: str,
    description: str,
    tzid: str | None,
    now: datetime,
    alarm_minutes: int = 0,
) -> list[str]:
    end = start + timedelta(minutes=minutes)
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "DTSTART" + _dt(start, tzid),
        "DTEND" + _dt(end, tzid),
        f"SUMMARY:{escape(summary)}",
        f"DESCRIPTION:{escape(description)}",
        "TRANSP:TRANSPARENT",
        "CATEGORIES:单词复习",
    ]
    lines += [
        "BEGIN:VALARM",
        f"TRIGGER:-PT{max(0, alarm_minutes)}M",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{escape(summary)}",
        "END:VALARM",
    ]
    lines.append("END:VEVENT")
    return lines


def summary_line(plan_items: list[Item]) -> str:
    names = [f"{item.list_id}·{item.label}" for item in plan_items]
    head = names[:3]
    tail = f" 等 {len(names)} 项" if len(names) > 3 else ""
    return "、".join(head) + tail


def build_ics(
    book: Book,
    now: datetime | None = None,
    days: int = 120,
    mode: str = "detail",
) -> str:
    """mode: digest（每天一条汇总）| detail（每个节点一条）| both"""
    now = now or datetime.now(book.tz)
    tzid = book.settings.get("timezone") or CHINA_TZ
    use_tz = tzid if tzid == CHINA_TZ else None

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//vocabcurve//单词记忆曲线//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:单词复习 · 词曲线",
        f"X-WR-TIMEZONE:{tzid}",
    ]
    lines += _vtimezone(tzid)

    plan = today_plan(book, now)
    day = now.date()
    for offset in range(days):
        target = day + timedelta(days=offset)
        items = items_on(book, target)
        if offset == 0:
            items = plan["overdue"] + items
        if not items and offset != 0:
            continue
        if not items:
            continue

        if mode in ("digest", "both"):
            digest_time = datetime.combine(target, book.remind_time, tzinfo=now.tzinfo)
            body = [f"今天 {len(items)} 项："]
            for item in items:
                body.append(f"{item.list_id} {item.title} · {item.label}")
            if offset == 0 and plan["overdue"]:
                body.append("含补做项，别跳轮次。")
            lines += _event(
                uid=f"vocabcurve-digest-{target:%Y%m%d}@vocabcurve",
                start=digest_time,
                minutes=20,
                summary=f"单词复习 · {target.month}月{target.day}日 · {len(items)} 项",
                description="\n".join(body),
                tzid=use_tz,
                now=now,
                alarm_minutes=0,
            )

        if mode in ("detail", "both"):
            for item in items:
                lines += _event(
                    uid=f"vocabcurve-{item.list_id}-{item.round}-{target:%Y%m%d}@vocabcurve",
                    start=item.due,
                    minutes=10,
                    summary=f"{item.list_id} {item.label} · {item.title}",
                    description=(
                        f"{item.title}\n{item.label}（共 {book.rounds} 轮）\n"
                        f"后续还有 {item.pending} 轮\n计划时刻 {item.due:%Y-%m-%d %H:%M}"
                    ),
                    tzid=use_tz,
                    now=now,
                    alarm_minutes=0,
                )

    lines.append("END:VCALENDAR")
    return "".join(fold(line) for line in lines)
