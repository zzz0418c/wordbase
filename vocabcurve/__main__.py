"""命令行入口：python -m vocabcurve ..."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .ics import build_ics
from .model import Book, parse_day
from .parse import guess_start_hint, load_source
from .render import (
    render_curve_md,
    render_html,
    render_plan_md,
    render_today_md,
    weekday,
)
from .schedule import (
    assign_starts,
    describe_curve,
    due_dt,
    mark_done,
    mark_undone,
    next_pending,
    offset_days,
    parse_intervals,
    progress_rows,
    set_progress,
    today_plan,
)
from .scan import apply_guess, guess, CIRCLED
from .vivo import load_notes, notebooks, select, to_lists


def _now(args, book: Book) -> datetime:
    if not getattr(args, "at", None):
        return datetime.now(book.tz)
    raw = str(args.at).strip().replace(" ", "T")
    if "T" in raw:
        return datetime.fromisoformat(raw).replace(tzinfo=book.tz)
    day = parse_day(raw)
    return datetime.combine(day, book.remind_time, tzinfo=book.tz)


def _load(args) -> Book:
    path = Path(args.book)
    if not path.exists():
        raise RuntimeError(f"找不到 {path}，先跑 `vocabcurve import <单词本>`")
    return Book.load(path)


def cmd_import(args) -> int:
    lists, report = load_source(args.source)
    path = Path(args.book)
    previous = Book.load(path) if (args.merge and path.exists()) else None

    book = Book(lists=lists)
    if previous:
        book.settings = dict(previous.settings)

    if args.intervals:
        book.settings["intervals"] = args.intervals.split(",")
    if args.grid:
        book.settings["grid"] = args.grid
    if args.mode:
        book.settings["mode"] = args.mode
    if args.remind:
        book.settings["remind_at"] = args.remind
    if args.per_day:
        book.settings["per_day"] = args.per_day
    parse_intervals(book.settings["intervals"])  # 提前校验，报错就别写盘
    if book.settings.get("grid") == "offsets":
        offset_days(book)

    kept = 0
    if previous:
        by_title = {item.title.strip(): item for item in previous.lists}
        for item in book.lists:
            old = by_title.get(item.title.strip())
            if old is None:
                continue
            item.done = dict(old.done)
            item.start = old.start or item.start
            kept += 1

    if args.start:
        start = parse_day(args.start)
    elif previous and previous.settings.get("start"):
        start = parse_day(previous.settings["start"])
    else:
        start = datetime.now(book.tz).date()

    book.settings["start"] = start.isoformat()
    assign_starts(book, start, book.settings.get("per_day") or 1)
    saved = book.save(path)

    print(f"✓ 解析出 {report.sections} 篇 / {report.entries} 词 → {saved}")
    if previous:
        print(f"  合并了 {kept} 篇的历史打卡（按标题匹配）")
    print(f"  篇目：{guess_start_hint(lists)}")
    print(f"  曲线：{describe_curve(book)}")
    print(f"  起始：{start.isoformat()}，每天 {book.settings['per_day']} 篇新词")
    for warning in report.warnings:
        print(f"  ! {warning}")
    print("\n下一步：`vocabcurve build` 生成今日页和日历提醒。")
    return 0


def cmd_brief(args) -> int:
    """一行到十行的纯文本日报，给推送用（微信/ntfy/邮件都能直接发）。"""
    book = _load(args)
    now = _now(args, book)
    plan = today_plan(book, now)
    print(brief_text(book, plan, now, show_overdue=not args.no_overdue))
    return 0


def brief_text(book: Book, plan: dict, now: datetime, show_overdue: bool = True) -> str:
    day = datetime.fromisoformat(plan["date"])
    head = f"📚 {day.month}月{day.day}日 {weekday(day)}"
    from .schedule import items_on

    # 今天「该做」的（按日期），不复用 today_plan —— 它会因为前面有一轮没打卡就把后面的轮次藏掉
    items = items_on(book, now.date())
    lines: list[str] = []
    if items:
        lines.append(f"{head} · 今天 {len(items)} 项")
        for item in items:
            lines.append(f"· {item.title}")
    else:
        lines.append(f"{head} · 今天没有复习任务")
    # 按要求：通知里不显示「补做」
    if plan.get("completed"):
        lines.append(f"✅ 已走完曲线 {len(plan['completed'])} 篇")
    if items:
        detail = f"{len(book.lists)} 篇在册"
        if book.word_count:
            detail += f"，共 {book.word_count} 词"
        lines.append(f"（{detail}）")
    synced = book.settings.get("last_sync")
    if synced:
        try:
            stamp = datetime.fromisoformat(str(synced))
            lines.append(f"笔记同步于 {stamp:%m-%d %H:%M}")
        except ValueError:
            pass
    return "\n".join(lines)


def cmd_push(args) -> int:
    """把日报推到 webhook：企业微信机器人 / Server酱 / ntfy / 自定义 JSON。"""
    import urllib.error
    import urllib.parse
    import urllib.request

    book = _load(args)
    now = _now(args, book)
    text = brief_text(book, today_plan(book, now), now, show_overdue=not getattr(args, "no_overdue", False))
    title = args.title or f"{now.month}月{now.day}日单词复习"

    if args.format == "wecom-app":
        return _push_wecom_app(args, text, title)

    if not args.url:
        if args.dry_run:
            print(text)
            return 0
        raise ValueError("要么给 --url，要么加 --dry-run 只打印")

    payload: bytes
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if args.format == "wecom":
        payload = json.dumps(
            {"msgtype": "text", "text": {"content": text}}, ensure_ascii=False
        ).encode("utf-8")
    elif args.format == "serverchan":
        payload = urllib.parse.urlencode({"title": title, "desp": text}).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
    elif args.format == "ntfy":
        payload = f"{title}\n{text}".encode("utf-8")
        headers = {"Content-Type": "text/plain; charset=utf-8"}
    else:
        payload = json.dumps({"title": title, "text": text}, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(args.url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read(200).decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        print(f"✗ 推送失败：{exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(text)
    print(f"✓ 已推送（{args.format}）：{body[:120]}")
    return 0


def _push_wecom_app(args, text: str, title: str) -> int:
    """企业微信自建应用 → 通过「微信插件」直接出现在个人微信聊天列表里。"""
    import os
    import urllib.error
    import urllib.parse
    import urllib.request

    corpid = args.corpid or os.environ.get("WECOM_CORPID")
    secret = args.secret or os.environ.get("WECOM_SECRET")
    agentid = args.agentid or os.environ.get("WECOM_AGENTID")
    touser = args.touser or os.environ.get("WECOM_TOUSER") or "@all"

    if args.dry_run:
        print(text)
        return 0

    if not (corpid and secret and agentid):
        raise ValueError("wecom-app 需要 --corpid / --secret / --agentid（或环境变量 WECOM_*）")

    token_url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken?" + urllib.parse.urlencode(
        {"corpid": corpid, "corpsecret": secret}
    )
    try:
        with urllib.request.urlopen(token_url, timeout=15) as response:
            token_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        print(f"✗ 取 access_token 失败：{exc}", file=sys.stderr)
        return 1
    if token_data.get("errcode"):
        print(f"✗ 企业微信返回：{token_data}", file=sys.stderr)
        return 1

    payload = json.dumps(
        {
            "touser": touser,
            "msgtype": "text",
            "agentid": int(agentid),
            "text": {"content": text},
            "safe": 0,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    send_url = (
        "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token="
        + urllib.parse.quote(str(token_data.get("access_token", "")))
    )
    request = urllib.request.Request(
        send_url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read(300).decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        print(f"✗ 发送失败：{exc}", file=sys.stderr)
        return 1

    if '"errcode":0' not in body.replace(" ", ""):
        print(f"✗ 企业微信返回：{body[:200]}", file=sys.stderr)
        return 1
    print(f"✓ 已推送到企业微信（微信插件）：{body[:120]}")
    return 0


def cmd_today(args) -> int:
    book = _load(args)
    now = _now(args, book)
    plan = today_plan(book, now)
    if args.json:
        payload = {
            "date": plan["date"],
            "now": plan["now"],
            "today": [_item_dict(x) for x in plan["today"]],
            "overdue": [_item_dict(x) for x in plan["overdue"]],
            "done_today": plan["done_today"],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(render_today_md(book, plan, now))
    return 0


def _item_dict(item) -> dict:
    return {
        "list_id": item.list_id,
        "title": item.title,
        "round": item.round,
        "due": item.due.isoformat(timespec="minutes"),
        "status": item.status,
        "pending": item.pending,
    }


def cmd_plan(args) -> int:
    book = _load(args)
    print(render_plan_md(book, _now(args, book), args.days))
    return 0


def cmd_curve(args) -> int:
    book = _load(args)
    print(render_curve_md(book, args.list_id))
    return 0


def cmd_check(args) -> int:
    book = _load(args)
    now = _now(args, book)
    item = book.find(args.list_id)
    done_item = mark_done(book, item.id, args.round, now)
    book.save(args.book)
    label = "首次学习" if args.round == 0 else f"第 {args.round} 轮"
    print(f"✓ {done_item.id} {done_item.title} · {label} 已打卡（{now:%Y-%m-%d %H:%M}）")
    nxt = _next_after(book, done_item)
    if nxt:
        print(f"  下一轮：{nxt[0]} · {nxt[1]:%Y-%m-%d %H:%M}")
    else:
        print("  这一篇走完曲线了 🎉")
    return 0


def _next_after(book: Book, item) -> tuple[str, datetime] | None:
    round_no = next_pending(item, book.rounds)
    if round_no is None:
        return None
    label = "首次学习" if round_no == 0 else f"第 {round_no} 轮"
    return label, due_dt(book, item, round_no)


def cmd_uncheck(args) -> int:
    book = _load(args)
    list_id = args.list_id if not args.list_id.isdigit() else f"L{int(args.list_id):02d}"
    mark_undone(book, list_id, args.round)
    book.save(args.book)
    print(f"✓ 已撤销 {args.list_id} 第 {args.round} 轮")
    return 0


def cmd_sync(args) -> int:
    """把今日页导出的 progress-*.json 写回 book.json。"""
    book = _load(args)
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    day = parse_day(payload.get("date") or datetime.now(book.tz).date())
    stamp = datetime.combine(day, book.remind_time, tzinfo=book.tz).isoformat(timespec="minutes")

    count = 0
    for row in payload.get("done") or []:
        try:
            mark_done(book, row["list_id"], int(row["round"]), datetime.fromisoformat(stamp))
            count += 1
        except (KeyError, ValueError, TypeError) as exc:
            print(f"  ! 跳过一行：{row}（{exc}）", file=sys.stderr)
    book.save(args.book)
    print(f"✓ 写回 {count} 条打卡")
    return 0


def cmd_ics(args) -> int:
    book = _load(args)
    text = build_ics(book, _now(args, book), args.days, args.mode)
    target = Path(args.out) if args.out else Path("out") / "vocabcurve.ics"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="")
    print(f"✓ {target}（{args.days} 天，{args.mode} 模式）")
    print("  平板：把这个文件发到平板，用日历 App 打开导入即可。")
    return 0


def cmd_build(args) -> int:
    book = _load(args)
    now = _now(args, book)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    plan = today_plan(book, now)

    (out / "today.md").write_text(render_today_md(book, plan, now), encoding="utf-8")
    (out / "plan.md").write_text(render_plan_md(book, now, args.days), encoding="utf-8")
    (out / "today.html").write_text(render_html(book, plan, now), encoding="utf-8")
    (out / "brief.txt").write_text(brief_text(book, plan, now) + "\n", encoding="utf-8")
    (out / "vocabcurve.ics").write_text(
        build_ics(book, now, args.days, args.ics_mode), encoding="utf-8", newline=""
    )

    total = plan["total_due"] + plan["total_overdue"]
    print(f"✓ 今日 {total} 项（积压 {plan['total_overdue']}，已完成 {len(plan.get('completed') or [])} 篇）")
    for path in ("today.md", "today.html", "plan.md", "brief.txt", "vocabcurve.ics"):
        print(f"  {out / path}")
    return 0


def cmd_serve(args) -> int:
    import functools
    import socket

    out = Path(args.out)
    if args.build:
        argv = argparse.Namespace(
            book=args.book,
            out=str(out),
            days=getattr(args, "days", 30),
            ics_mode=getattr(args, "ics_mode", "detail"),
            at=getattr(args, "at", None),
        )
        cmd_build(argv)
    if not out.exists():
        print("先跑 `vocabcurve build` 生成页面", file=sys.stderr)
        return 2

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(out))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    host_ip = "127.0.0.1"
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        host_ip = sock.getsockname()[0]
        sock.close()
    except OSError:
        pass
    print(f"今日页：http://127.0.0.1:{args.port}/today.html")
    if args.host == "0.0.0.0":
        print(f"平板访问：http://{host_ip}:{args.port}/today.html")
    print("Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


def cmd_info(args) -> int:
    book = _load(args)
    print(f"vocabcurve {__version__}")
    print(f"篇目 {len(book.lists)} 篇 / {book.word_count} 词")
    print(f"曲线 {describe_curve(book)}")
    print(f"模式 {book.mode}　提醒 {book.settings.get('remind_at')}　起始 {book.settings.get('start')}")
    per_day = book.settings.get("per_day") or 1
    print(f"每天 {per_day} 篇新词")
    plan = today_plan(book)
    print(f"今天 {plan['total_due']} 项，积压 {plan['total_overdue']}")
    return 0


def _persist(args, lists, headline: str) -> Book:
    """把解析好的篇目落盘：沿用旧设置、按标题合并打卡、铺开始日期。"""
    path = Path(args.book)
    previous = Book.load(path) if (getattr(args, "merge", False) and path.exists()) else None
    book = Book(lists=lists)
    if previous:
        book.settings = dict(previous.settings)

    if getattr(args, "intervals", None):
        book.settings["intervals"] = args.intervals.split(",")
    if getattr(args, "grid", None):
        book.settings["grid"] = args.grid
    if getattr(args, "remind", None):
        book.settings["remind_at"] = args.remind
    if getattr(args, "per_day", None):
        book.settings["per_day"] = args.per_day
    if book.settings.get("grid") == "offsets":
        offset_days(book)

    kept = 0
    if previous:
        by_title = {item.title.strip(): item for item in previous.lists}
        for item in book.lists:
            old = by_title.get(item.title.strip())
            if old is None:
                continue
            item.done = dict(old.done)
            item.start = old.start or item.start
            kept += 1

    if getattr(args, "start", None):
        start = parse_day(args.start)
    elif previous and previous.settings.get("start"):
        start = parse_day(previous.settings["start"])
    else:
        start = datetime.now(book.tz).date()

    book.settings["start"] = start.isoformat()
    assign_starts(book, start, book.settings.get("per_day") or 1)
    book.save(path)

    print(headline)
    if previous:
        print(f"  合并了 {kept} 篇的历史打卡（按标题匹配）")
    print(f"  曲线：{describe_curve(book)}")
    print(f"  起始：{start.isoformat()}，每天 {book.settings['per_day']} 篇")
    return book


def cmd_vivo(args) -> int:
    notes = load_notes(Path(args.db) if args.db else None)

    if args.action == "list":
        print(f"读到 {len(notes)} 条笔记：")
        for name, count in notebooks(notes):
            print(f"  {count:>3}  {name}")
        picked = select(notes, args.notebook, args.pattern)
        if args.show or args.notebook or args.pattern:
            print(f"\n匹配 {len(picked)} 条：")
            for note in picked[:80]:
                flag = "图片" if note.is_image else "文本"
                print(f"  {note.id:>4} [{flag}] {note.title}   《{note.notebook}》")
        else:
            print("\n加 --notebook / --pattern 看具体篇目，例如：")
            print("  vocabcurve vivo list --notebook 雅思词汇 --show")
        return 0

    picked = select(notes, args.notebook, args.pattern)
    if not picked:
        raise ValueError("没有匹配到笔记，先用 `vocabcurve vivo list --show` 看看标题")
    lists = to_lists(picked)
    book = _persist(
        args,
        lists,
        headline=f"✓ 从原子笔记导入 {len(lists)} 篇（{picked[0].notebook or '未分类'}）",
    )
    print(f"  篇目：{lists[0].title} … {lists[-1].title}")
    if all(not item.words for item in book.lists):
        print("  ! 这些是图片笔记，词表只有 OCR 文本，已按篇排程；复习时回原子笔记看原文。")
    print("\n下一步：`vocabcurve build` 重新生成今日页和日历。")
    return 0


def _parse_numbers(token: str) -> list[int]:
    token = token.strip().upper().replace("L", "").replace("第", "").replace("篇", "")
    if "-" in token:
        head, _, tail = token.partition("-")
        return list(range(int(head), int(tail) + 1))
    return [int(token)]


def _apply_spec(book: Book, token: str, now: datetime) -> None:
    """解析 `16=2` / `1-15=done` / `16=-` / `16=2026-10-12` 这样的进度指令。"""
    left, sep, right = token.partition("=")
    if not sep:
        raise ValueError(f"看不懂 {token!r}，应该是 16=2 这样的写法")
    ids = [f"L{number:02d}" for number in _parse_numbers(left)]
    value = right.strip().lower()

    if value in {"done", "complete", "完成", "已完成"}:
        for list_id in ids:
            set_progress(book, list_id, book.rounds, now)
    elif value in {"-", "none", "未开始", "none"}:
        for list_id in ids:
            set_progress(book, list_id, None, now)
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        for list_id in ids:
            item = book.find(list_id)
            item.done.clear()
            item.start = value
    else:
        try:
            last_round = int(value)
        except ValueError as exc:
            raise ValueError(f"看不懂 {token!r} 右边的 {right!r}") from exc
        for list_id in ids:
            set_progress(book, list_id, last_round, now)


def _display_width(text: str) -> int:
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def cmd_progress(args) -> int:
    book = _load(args)
    now = _now(args, book)
    if args.specs:
        for spec in args.specs:
            _apply_spec(book, spec, now)
        # 没开始的篇：从"下一个能学的日子"起按顺序铺
        next_day = now.date() if now.time() < book.remind_time else now.date() + timedelta(days=1)
        assign_starts(book, next_day, book.settings.get("per_day") or 1)
        book.save(args.book)
        print(f"✓ 已更新 {len(args.specs)} 组进度\n")

    rows = progress_rows(book, now)
    print(
        _pad("篇", 6) + _pad("标题", 26) + _pad("状态", 10)
        + _pad("已完成到", 14) + _pad("下次", 10) + "剩余"
    )
    for row in rows:
        last = row["last_round"]
        if row["state"] == "已完成":
            done_label = "全部"
        elif last < 0:
            done_label = "—"
        else:
            done_label = "首次学习" if last == 0 else f"第 {last} 轮"
        nxt = row["next_due"].strftime("%m-%d") if row["next_due"] else "—"
        print(
            _pad(row["id"], 6) + _pad(row["title"], 26) + _pad(row["state"], 10)
            + _pad(done_label, 14) + _pad(nxt, 10) + str(row["remaining"])
        )
    print("\n改进度：`vocabcurve progress 16=2 17=1 18=0 19=-`（数字=已完成的最后一轮，-=未开始，done=完成）")
    print("改完记得 `vocabcurve build` 重新生成日历。")
    return 0


def cmd_order(args) -> int:
    """设定新学顺序：比如先 16-22 再 1-15。"""
    book = _load(args)
    now = _now(args, book)
    sequence: list[str] = []
    for chunk in " ".join(args.sequence).replace("，", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        for number in _parse_numbers(chunk):
            list_id = f"L{number:02d}"
            book.find(list_id)  # 不存在就直接报错
            if list_id not in sequence:
                sequence.append(list_id)

    if not sequence:
        raise ValueError("至少给一个顺序，比如 16-22,1-15")

    book.settings["order"] = sequence
    next_day = now.date() if now.time() < book.remind_time else now.date() + timedelta(days=1)
    for item in book.lists:  # 还没开始的重新按顺序铺
        if not item.done:
            item.start = None
    assigned = assign_starts(book, next_day, book.settings.get("per_day") or 1, sequence)
    book.save(args.book)

    print(f"✓ 学习顺序：{' → '.join(sequence)}")
    if assigned:
        print(f"  已为 {len(assigned)} 篇未开始的排期：{assigned[0].title}（{assigned[0].start}）起")
    else:
        print("  当前没有未开始的篇，顺序只影响以后新增的篇")
    return 0


def cmd_scan(args) -> int:
    """从每篇笔记第一页的日期+圈号，自动推测复习进度。"""
    book = _load(args)
    now = _now(args, book)
    today = now.date()
    notes = load_notes(Path(args.db) if args.db else None)
    by_title: dict[str, object] = {}
    for note in notes:
        if note.title:
            by_title.setdefault(note.title.strip(), note)

    from .schedule import offset_days

    offsets = offset_days(book)
    rows = []
    missing: list[str] = []
    for item in book.lists:
        note = by_title.get(item.title.strip())
        if note is None:
            missing.append(item.id)
            rows.append((item, None))
            continue
        rows.append((item, guess(note.first_page, today, offsets)))

    print(
        _pad("篇", 6) + _pad("标题", 26) + _pad("圈号", 8)
        + _pad("推断", 10) + _pad("吻合", 6) + _pad("上次", 8) + "你写的下次"
    )
    applied = 0
    for item, result in rows:
        if result is None:
            print(_pad(item.id, 6) + _pad(item.title, 26) + "（原子笔记里没找到同名笔记）")
            continue
        circles = "".join(CIRCLED[value - 1] for value in result.circles if value <= 10)
        last_label = result.last_date.strftime("%m-%d") if result.last_date else "—"
        if result.rounds is None:
            label = "未开始"
        else:
            label = "首学" if result.rounds == 0 else f"第 {result.rounds} 轮"
        conf_label = str(result.confidence) if result.confidence else "—"
        next_label = result.next_date.strftime("%m-%d") if result.next_date else "—"
        print(
            _pad(item.id, 6) + _pad(item.title, 26) + _pad(circles or "—", 8)
            + _pad(label, 10) + _pad(conf_label, 6) + _pad(last_label, 8) + next_label
        )
        if args.apply and result.rounds is not None and result.last_date:
            apply_guess(
                book, item.id, result.rounds, result.last_date, today,
                next_date=result.next_date,
                start_date=result.start_hint or (result.dates[0] if result.dates else None),
            )
            applied += 1
        elif args.apply:
            # 第一页上什么都没读到，就当成还没开始（别留着上一次的假进度）
            item.done.clear()
            item.start = None

    if args.apply:
        next_day = today if now.time() < book.remind_time else today + timedelta(days=1)
        order = book.settings.get("order") or None
        assign_starts(book, next_day, book.settings.get("per_day") or 1, order)
        book.save(args.book)
        print(f"\n✓ 已按扫描结果写回 {applied} 篇（没扫描到进度的保持未开始）")
        print("  下一步：`vocabcurve build` 重新生成日历")
    else:
        print("\n这是预演，没有改任何数据。确认无误后加 --apply 写回。")
    if missing:
        print(f"  ! 没找到笔记：{', '.join(missing)}")
    return 0


def cmd_done(args) -> int:
    """今天该做的（含逾期）一次性全部打卡。"""
    book = _load(args)
    now = _now(args, book)
    plan = today_plan(book, now)
    items = list(plan["overdue"]) + list(plan["due_now"])
    for item in items:
        mark_done(book, item.list_id, item.round, now)
    book.save(args.book)
    if not items:
        print("今天本来就没有任务")
        return 0
    print(f"✓ 已打卡 {len(items)} 项：")
    for item in items:
        print(f"  {item.list_id} {item.label}")
    return 0


def cmd_next(args) -> int:
    """直接指定某一篇的下次复习日期：next 8=10-22 10=10-20"""
    book = _load(args)
    now = _now(args, book)
    from .schedule import offset_days

    offsets = offset_days(book)
    for spec in args.specs:
        left, sep, right = spec.partition("=")
        if not sep:
            raise ValueError(f"看不懂 {spec!r}，应该是 8=10-22 这样")
        raw = right.strip().replace(".", "-").replace("/", "-")
        if re.fullmatch(r"\d{1,2}-\d{1,2}", raw):
            month, day = (int(part) for part in raw.split("-"))
            target = date(now.year, month, day)
        else:
            target = parse_day(raw)
        for number in _parse_numbers(left):
            item = book.find(f"L{number:02d}")
            done = [int(k) for k in item.done if k.isdigit()]
            last = max(done) if done else -1
            nxt = last + 1
            if nxt > book.rounds:
                raise ValueError(f"{item.id} 已经走完曲线了")
            start = target - timedelta(days=offsets[nxt - 1])
            item.start = start.isoformat()
            print(f"✓ {item.id} {item.title}：下次复习 {target:%m-%d}（第 {nxt} 轮）")
    book.save(args.book)
    return 0


def cmd_sync_vivo(args) -> int:
    """读今天的原子笔记，看看今天该复习的篇目里哪些已经记上了日期。"""
    import os
    import subprocess

    book = _load(args)
    now = _now(args, book)
    today = now.date()
    notes = load_notes(Path(args.db) if args.db else None)
    by_title = {note.title.strip(): note for note in notes if note.title}

    pattern = re.compile(rf"{today.month}\s*[.。:：、,\-]\s*{today.day}(?!\d)")
    plan = today_plan(book, now)
    from .schedule import next_pending, offset_days
    from .scan import guess

    offsets = offset_days(book)

    # 先把每篇「下次复习日」对齐到你笔记里写的那个日期，再判断今天做什么
    realigned = 0
    for item in book.lists:
        note = by_title.get(item.title.strip())
        if note is None:
            continue
        info = guess(note.first_page, today, offsets)
        if not info.next_date or info.next_date < today:
            continue
        pending_round = next_pending(item, book.rounds)
        if pending_round is None or pending_round < 1:
            continue
        offset = offsets[pending_round - 1]
        new_start = (info.next_date - timedelta(days=offset)).isoformat()
        if new_start != item.start:
            item.start = new_start
            realigned += 1
    if realigned:
        print(f"✓ 按笔记里写的下次日期，重新对齐了 {realigned} 篇")

    targets = list(plan["due_now"]) + list(plan.get("later") or []) + list(plan["overdue"])

    marked: list[str] = []
    seen: set[str] = set()
    for item in targets:
        if item.list_id in seen:
            continue
        note = by_title.get(item.title.strip())
        if note is None or not pattern.search(note.first_page):
            continue
        seen.add(item.list_id)
        mark_done(book, item.list_id, item.round, now)
        marked.append(f"{item.list_id} {item.title}")

    book.settings["last_sync"] = now.isoformat(timespec="minutes")
    book.save(args.book)

    print(f"✓ 扫描 {len(targets)} 项，发现今天已记录 {len(marked)} 项")
    for line in marked:
        print(f"  · {line}")

    if args.push:
        repo = Path(__file__).resolve().parents[1]
        commands = [
            ["git", "-c", f"user.name=vocabcurve", "-c", f"user.email=vocabcurve@local", "add", "-A"],
            ["git", "-c", "user.name=vocabcurve", "-c", "user.email=vocabcurve@local",
             "commit", "-m", f"chore: 笔记同步 {now:%m-%d %H:%M}"],
            ["git", "-c", "http.sslVerify=false", "push", "origin", "HEAD"],
        ]
        for command in commands:
            env = dict(os.environ)
            env.update({
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "never",
            })
            result = subprocess.run(
                command, cwd=str(repo), capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=env, timeout=120,
            )
            if result.returncode != 0 and "nothing to commit" not in (result.stdout + result.stderr):
                print(f"  ! {' '.join(command[:3])} 失败：{result.stderr.strip()[:120]}")
                return 1
        print("✓ 已推送到 GitHub")
    return 0


def report_text(book: Book, plan: dict, now: datetime) -> str:
    """晚上 20:00 的复盘：今天记了没有、漏了哪几篇、明天是什么。"""
    day = datetime.fromisoformat(plan["date"])
    head = f"🌙 {day.month}月{day.day}日 {weekday(day)} · 今日复习"

    from .schedule import items_on

    pending = items_on(book, now.date())
    done_today = plan["done_today"]
    overdue = [x for x in plan["overdue"] if all(x.list_id != p.list_id for p in pending)]
    synced = book.settings.get("last_sync")
    sync_day = None
    if synced:
        try:
            sync_day = datetime.fromisoformat(str(synced)).date()
        except ValueError:
            sync_day = None

    lines = [head]
    if sync_day != now.date():
        lines.append("⚠️ 今天电脑没有同步过笔记，请检查今日复习进度：")
        for item in pending:
            lines.append(f"· {item.title}")
        if not pending:
            lines.append("· （今天本来没有安排）")
    else:
        lines.append(f"今天记上了 {len(done_today)} 项，今天该做 {len(pending) + len(done_today)} 项")
        for item in pending:
            lines.append(f"⬜ {item.title}")
        if pending:
            lines.append("⚠️ 有遗漏，睡前补一下")
        else:
            lines.append("✅ 今天的都完成了")

    tomorrow = now.date() + timedelta(days=1)
    from .schedule import items_on

    # 和早上完全同一套规则：明天到期的全部列出（不看是不是有更早的逾期）
    upcoming = items_on(book, tomorrow)
    if upcoming:
        lines.append("📅 明天：" + "、".join(item.title for item in upcoming))
    else:
        lines.append("📅 明天：没有安排")
    return "\n".join(lines)


def cmd_report(args) -> int:
    import os
    import urllib.request

    book = _load(args)
    now = _now(args, book)
    text = report_text(book, today_plan(book, now), now)

    if not args.push:
        print(text)
        return 0

    url = args.url or os.environ.get("WECOM_WEBHOOK")
    if not url:
        raise ValueError("需要 --url 或环境变量 WECOM_WEBHOOK")

    payload = json.dumps({"msgtype": "text", "text": {"content": text}}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read(200).decode("utf-8", "replace")
    print(f"✓ 已推送晚间复盘：{body[:100]}")
    return 0




DEFAULT_WEBHOOK = ""


def _post_wecom(url: str, text: str) -> str:
    import urllib.request

    payload = json.dumps({"msgtype": "text", "text": {"content": text}}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read(200).decode("utf-8", "replace")


def cmd_notify(args) -> int:
    """本地按时发一条（早上/晚上），并把「已发」写进仓库，云端看到就不会重复发。"""
    import os
    import subprocess

    book = _load(args)
    now = _now(args, book)
    plan = today_plan(book, now)
    if args.slot == "morning":
        text = brief_text(book, plan, now)
        state_rel = "state/last-sent.txt"
    else:
        text = report_text(book, plan, now)
        state_rel = "state/last-report.txt"

    print(text)
    if args.dry_run:
        return 0

    repo = Path(__file__).resolve().parents[1]
    state = repo / state_rel
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"})

    # 先同步远端去重标记：云端的定时任务如果已经发过，这里就不再发
    subprocess.run(
        ["git", "-c", "http.sslVerify=false", "pull", "--rebase", "-q", "origin", "main"],
        cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=90,
    )
    try:
        if state.read_text(encoding="utf-8").strip() == now.date().isoformat():
            print("今天已经发过了，跳过")
            return 0
    except FileNotFoundError:
        pass

    url = args.url or os.environ.get("WECOM_WEBHOOK") or DEFAULT_WEBHOOK
    print("✓ " + _post_wecom(url, text)[:100])

    if args.no_push:
        return 0

    state.parent.mkdir(exist_ok=True)
    state.write_text(now.date().isoformat() + "\n", encoding="utf-8")

    commands = [
        ["git", "add", state_rel],
        ["git", "commit", "-m", f"chore: 本地已发 {state_rel} {now:%m-%d %H:%M}"],
        ["git", "-c", "http.sslVerify=false", "pull", "--rebase", "origin", "main"],
        ["git", "-c", "http.sslVerify=false", "push", "origin", "HEAD:main"],
    ]
    for command in commands:
        result = subprocess.run(
            command, cwd=str(repo), capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env, timeout=120,
        )
        if result.returncode != 0 and "nothing to commit" not in (result.stdout + result.stderr):
            print(f"  ! {' '.join(command[:2])} 失败（不影响已发送）：{result.stderr.strip()[:100]}")
            break
    return 0




def cmd_sync_dates(args) -> int:
    """扫每篇笔记的所有页，把「下次 10.27」写进 schedule.csv。"""
    from .nextdate import explicit_next

    book = _load(args)
    now = _now(args, book)
    today = now.date()
    notes = load_notes(Path(args.db) if args.db else None)
    by_title = {note.title.strip(): note for note in notes if note.title}

    csv_path = Path(args.csv)
    existing: dict[str, str] = {}
    if csv_path.exists():
        for line in csv_path.read_text(encoding="utf-8").splitlines():
            parts = line.split(",")
            if len(parts) >= 2 and parts[0].strip() and parts[0].strip() != "title":
                existing[parts[0].strip()] = parts[1].strip()

    found: dict[str, str] = {}
    for item in book.lists:
        note = by_title.get(item.title.strip())
        if note is None:
            continue
        for page in note.pages:
            value = explicit_next(page, today)
            if value:
                found[item.title.strip()] = value.isoformat()
                break

    merged = dict(existing)
    merged.update(found)

    lines = ["title,next_date"]
    for item in book.lists:
        key = item.title.strip()
        if key in merged:
            lines.append(f"{key},{merged[key]}")
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if args.push:
        import subprocess
        repo = Path(__file__).resolve().parents[1]
        env = dict(os.environ); env.update({"GIT_TERMINAL_PROMPT":"0","GCM_INTERACTIVE":"never"})
        for cmd in (["git","add","schedule.csv"],
                    ["git","commit","-m",f"chore: 笔记里的下次日期 {now:%m-%d %H:%M}"],
                    ["git","-c","http.sslVerify=false","push","origin","HEAD:main"]):
            r = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=90)
            if r.returncode != 0 and "nothing to commit" not in (r.stdout+r.stderr):
                print("  ! 推送失败：", r.stderr.strip()[:100]); break
        else:
            print("✓ 已推送到 GitHub")

    print(f"✓ 从笔记里读到 {len(found)} 篇的「下次」日期，写进 {csv_path}")
    for item in book.lists:
        key = item.title.strip()
        mark = "← 笔记" if key in found else ""
        print(f"  {key}: {merged.get(key, '—')} {mark}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vocabcurve",
        description="把单词本按固定记忆曲线排程，并导出每日提醒。",
    )
    parser.add_argument("--book", default="book.json", help="数据文件（默认 book.json）")
    parser.add_argument("--version", action="version", version=f"vocabcurve {__version__}")
    subs = parser.add_subparsers(dest="command", required=True)

    p = subs.add_parser("import", help="导入单词本（txt/md/csv/xlsx/docx 或 stdin 文本）")
    p.add_argument("source")
    p.add_argument("--start", help="第一天学习日期，默认今天")
    p.add_argument(
        "--intervals",
        help="复习节点。offsets 模式写天：1,2,4,7,15,30；relative 模式写间隔：30m,12h,1d",
    )
    p.add_argument("--grid", choices=["offsets", "relative"], help="节点含义，默认 offsets")
    p.add_argument("--mode", choices=["strict", "adaptive"])
    p.add_argument("--remind", help="每天提醒时刻 HH:MM，默认 08:00")
    p.add_argument("--per-day", type=int, help="每天学几篇新词，默认 1")
    p.add_argument(
        "--merge",
        action="store_true",
        help="按标题合并已有 book.json，保留历史打卡（新增篇目时用）",
    )
    p.set_defaults(func=cmd_import)

    p = subs.add_parser(
        "vivo",
        help="直接读 vivo 办公套件同步下来的原子笔记（平板不用操作）",
    )
    p.add_argument("action", choices=["list", "import"], help="list=看看有哪些笔记，import=导入")
    p.add_argument("--notebook", help="按笔记本名筛选，如 雅思词汇")
    p.add_argument("--pattern", help="按标题正则筛选，如 ^3\\.1\\.")
    p.add_argument("--show", action="store_true", help="list 时把笔记标题也列出来")
    p.add_argument("--db", help="手动指定 NoteSync.db 路径")
    p.add_argument("--start", help="第一篇哪天学，默认今天")
    p.add_argument("--per-day", type=int, help="每天几篇，默认 1")
    p.add_argument("--intervals")
    p.add_argument("--grid", choices=["offsets", "relative"])
    p.add_argument("--remind")
    p.add_argument("--merge", action="store_true", help="按标题合并，保留历史打卡")
    p.set_defaults(func=cmd_vivo)

    p = subs.add_parser("progress", help="看/改每篇的复习进度（从第几篇开始、各自到第几轮）")
    p.add_argument("specs", nargs="*", help="16=2 表示第16篇已完成到第2轮；1-15=done；16=- 表示未开始")
    p.add_argument("--at", help="以哪一天为准，默认现在")
    p.set_defaults(func=cmd_progress)

    p = subs.add_parser("next", help="直接指定下次复习日期：next 8=10-22")
    p.add_argument("specs", nargs="+")
    p.add_argument("--at")
    p.set_defaults(func=cmd_next)

    p = subs.add_parser("done", help="今天该做的全部打卡")
    p.add_argument("--at")
    p.set_defaults(func=cmd_done)

    p = subs.add_parser("order", help="设定新学顺序，比如先 16-22 再 1-15")
    p.add_argument("sequence", nargs="+", help="例如 16-22,1-15")
    p.add_argument("--at")
    p.set_defaults(func=cmd_order)

    p = subs.add_parser("notify", help="本地定时发送（早上/晚上），并同步去重标记")
    p.add_argument("slot", choices=["morning", "evening"])
    p.add_argument("--url")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-push", action="store_true")
    p.add_argument("--at")
    p.set_defaults(func=cmd_notify)

    p = subs.add_parser("report", help="晚上 20:00 的复盘：今天漏了哪几篇")
    p.add_argument("--push", action="store_true", help="直接发到企业微信")
    p.add_argument("--url", help="企业微信 webhook（默认读 WECOM_WEBHOOK）")
    p.add_argument("--at")
    p.set_defaults(func=cmd_report)

    p = subs.add_parser("sync-dates", help="从笔记里读「下次 10.27」写入 schedule.csv")
    p.add_argument("--csv", default="schedule.csv")
    p.add_argument("--push", action="store_true", help="写完顺手推 GitHub")
    p.add_argument("--db")
    p.add_argument("--at")
    p.set_defaults(func=cmd_sync_dates)

    p = subs.add_parser("sync-vivo", help="读今天的原子笔记，自动勾掉今天已复习的篇目")
    p.add_argument("--push", action="store_true", help="改完顺手 git push 到 GitHub")
    p.add_argument("--db")
    p.add_argument("--at")
    p.set_defaults(func=cmd_sync_vivo)

    p = subs.add_parser("scan", help="从笔记第一页的日期+圈号自动读进度")
    p.add_argument("--apply", action="store_true", help="真的写回（默认只预演）")
    p.add_argument("--db")
    p.add_argument("--at")
    p.set_defaults(func=cmd_scan)

    p = subs.add_parser("today", help="今日任务")
    p.add_argument("--at", help="假装现在是这个时间（调试/补看）")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_today)

    p = subs.add_parser("brief", help="纯文本日报（给推送用）")
    p.add_argument("--no-overdue", action="store_true", help="不显示补做项")
    p.add_argument("--at")
    p.set_defaults(func=cmd_brief)

    p = subs.add_parser("push", help="把日报推到 webhook（企业微信/Server酱/ntfy）")
    p.add_argument("--url", help="webhook 地址；不给就只打印")
    p.add_argument(
        "--format",
        choices=["wecom-app", "wecom", "serverchan", "ntfy", "json"],
        default="wecom",
        help="企业微信群机器人=wecom（默认），Server酱=serverchan，ntfy=ntfy",
    )
    p.add_argument("--title")
    p.add_argument("--corpid", help="企业微信 corpid（wecom-app 用）")
    p.add_argument("--secret", help="自建应用 Secret")
    p.add_argument("--agentid", help="自建应用 AgentId")
    p.add_argument("--touser", help="接收人 userid，默认 @all")
    p.add_argument("--dry-run", action="store_true", help="只打印要发的内容，不真的发")
    p.add_argument("--no-overdue", action="store_true", help="不显示补做项（云端用，避免和本地打卡不同步）")
    p.add_argument("--at")
    p.set_defaults(func=cmd_push)

    p = subs.add_parser("plan", help="未来几天的时间表")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--at")
    p.set_defaults(func=cmd_plan)

    p = subs.add_parser("curve", help="看某一篇的完整曲线")
    p.add_argument("list_id", nargs="?")
    p.set_defaults(func=cmd_curve)

    p = subs.add_parser("check", help="给某篇某一轮打卡")
    p.add_argument("list_id")
    p.add_argument("round", type=int)
    p.add_argument("--at")
    p.set_defaults(func=cmd_check)

    p = subs.add_parser("uncheck", help="撤销打卡")
    p.add_argument("list_id")
    p.add_argument("round", type=int)
    p.set_defaults(func=cmd_uncheck)

    p = subs.add_parser("sync", help="把今日页导出的 progress-*.json 写回")
    p.add_argument("file")
    p.set_defaults(func=cmd_sync)

    p = subs.add_parser("ics", help="生成日历文件")
    p.add_argument("--days", type=int, default=120)
    p.add_argument("--mode", choices=["digest", "detail", "both"], default="digest")
    p.add_argument("-o", "--out")
    p.add_argument("--at")
    p.set_defaults(func=cmd_ics)

    p = subs.add_parser("build", help="一次性生成 today.md / today.html / plan.md / .ics")
    p.add_argument("--out", default="out")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--ics-mode", choices=["digest", "detail", "both"], default="digest")
    p.add_argument("--at")
    p.set_defaults(func=cmd_build)

    p = subs.add_parser("serve", help="起个本地小服务，让平板浏览器打开今日页")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--out", default="out")
    p.add_argument("--build", action="store_true", help="启动前先生成")
    p.set_defaults(func=cmd_serve)

    p = subs.add_parser("info", help="看一眼当前配置")
    p.set_defaults(func=cmd_info)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (KeyError, ValueError, RuntimeError, OSError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
