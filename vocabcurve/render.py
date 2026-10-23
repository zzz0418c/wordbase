"""把排程渲染成人能看的东西：Markdown 看板、时间表，以及离线可用的今日页。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from .model import Book, WordList
from .schedule import Item, curve_for, items_on, pending_count

WEEKDAYS = "一二三四五六日"


def weekday(day: date) -> str:
    return f"周{WEEKDAYS[day.weekday()]}"


def cn_day(day: date) -> str:
    return f"{day.month}月{day.day}日"


def _preview(item: WordList, limit: int = 4) -> str:
    if not item.words:
        return "（图片笔记，去原子笔记里背）"
    words = "、".join(word.term for word in item.words[:limit])
    more = "…" if item.size > limit else ""
    return f"{words}{more}"


def render_today_md(book: Book, plan: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(book.tz)
    day = date.fromisoformat(plan["date"])
    out: list[str] = [
        f"# {day.isoformat()} {weekday(day)} · 今日任务",
        "",
        f"> 共 **{plan['total_due']}** 项"
        + (f"，积压 **{plan['total_overdue']}** 篇" if plan["total_overdue"] else "")
        + f" · 曲线 {book.settings.get('mode')} 模式",
        "",
    ]

    def block(title: str, items: list[Item], mark: str = " ") -> None:
        if not items:
            return
        out.append(f"## {title}")
        out.append("")
        for item in items:
            when = item.due.strftime("%m-%d %H:%M")
            extra = f" · 后续还有 {item.pending} 轮" if item.pending else ""
            out.append(f"- [{mark}] `{item.list_id}` {item.title} · **{item.label}** · {when}{extra}")
        out.append("")

    block("到点", plan.get("due_now") or [], " ")
    block("今天稍后", plan.get("later") or [], " ")
    block("积压（先补这个）", plan["overdue"], " ")
    if plan.get("completed"):
        rows = plan["completed"]
        out.append(f"## 已完成（{len(rows)} 篇，不再提醒）")
        out.append("")
        for list_id, title, done_on, missing in rows[:3]:
            note = f"（有 {missing} 个节点没打卡）" if missing else ""
            out.append(f"- ✅ `{list_id}` {title} · {done_on:%m-%d} 走完曲线{note}")
        if len(rows) > 3:
            out.append(f"- … 另外 {len(rows) - 3} 篇也已完成")
        out.append("")
    if plan["done_today"]:
        out.append("## 今天已完成")
        out.append("")
        for list_id, round_no, stamp in plan["done_today"]:
            label = "首次学习" if round_no == 0 else f"第 {round_no} 轮"
            out.append(f"- [x] `{list_id}` {label} · {stamp[11:16]}")
        out.append("")

    if not plan["today"] and not plan["overdue"] and not plan["done_today"]:
        out.append("今天没有任务，休息或者提前预习明天的篇目。")
        out.append("")

    new_items = [x for x in plan["today"] if x.round == 0]
    if new_items:
        out.append("## 今天的新词预览")
        out.append("")
        for item in new_items:
            target = next(lst for lst in book.lists if lst.id == item.list_id)
            out.append(f"- `{item.list_id}` {_preview(target, 6)}（共 {target.size} 词）")
        out.append("")

    out.append("---")
    out.append(f"打卡：`vocabcurve check <篇号> <轮次>`　重新生成：`vocabcurve build`")
    return "\n".join(out) + "\n"


def render_plan_md(book: Book, now: datetime | None = None, days: int = 30) -> str:
    now = now or datetime.now(book.tz)
    out = [
        f"# 未来 {days} 天时间表",
        "",
        f"曲线：{len(book.settings.get('intervals') or [])} 个节点　模式：{book.settings.get('mode')}",
        "",
        "| 日期 | 星期 | 数量 | 内容 |",
        "| --- | --- | --- | --- |",
    ]
    total = 0
    for offset in range(days):
        day = now.date() + timedelta(days=offset)
        items = items_on(book, day)
        total += len(items)
        if not items:
            continue
        detail = "、".join(f"{x.list_id}{x.label}" for x in items[:4])
        if len(items) > 4:
            detail += f" 等 {len(items)} 项"
        out.append(f"| {day.isoformat()} | {weekday(day)} | {len(items)} | {detail} |")
    out += ["", f"合计 {total} 项。", ""]
    return "\n".join(out)


def render_curve_md(book: Book, list_id: str | None = None) -> str:
    targets = [book.find(list_id)] if list_id else book.lists
    out: list[str] = []
    for item in targets:
        out.append(f"## {item.id} {item.title}（{item.size} 词）")
        out.append("")
        out.append("| 轮次 | 计划 | 状态 |")
        out.append("| --- | --- | --- |")
        for round_no, due, actual in curve_for(book, item):
            label = "首次学习" if round_no == 0 else f"第 {round_no} 轮"
            status = f"✅ {actual[5:16].replace('T', ' ')}" if actual else "待做"
            out.append(f"| {label} | {due:%Y-%m-%d %H:%M} | {status} |")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- HTML

_CSS = """
:root{--paper:#fbf8f3;--ink:#1e1a15;--muted:#8a7f72;--line:#e6ddd0;--accent:#b5522f;--ok:#3f7a52;--warn:#b5522f;--card:#fffdf9}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;padding:28px 18px 64px}
.wrap{max-width:720px;margin:0 auto}
header{margin-bottom:22px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:.5px}
h1 span{color:var(--muted);font-size:16px;font-weight:400;margin-left:8px}
.sub{color:var(--muted);margin:0;font-size:14px}
.bar{height:6px;background:var(--line);border-radius:99px;margin:18px 0 26px;overflow:hidden}
.bar>i{display:block;height:100%;width:0;background:var(--ok);transition:width .3s}
h2{font-size:14px;letter-spacing:2px;color:var(--muted);font-weight:600;margin:26px 0 10px}
.card{display:flex;gap:14px;align-items:flex-start;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:10px;transition:opacity .2s}
.card.done{opacity:.45}
.card.done .title{text-decoration:line-through}
.check{flex:0 0 22px;width:22px;height:22px;border-radius:50%;border:2px solid var(--line);margin-top:3px;cursor:pointer;background:transparent}
.card.done .check{background:var(--ok);border-color:var(--ok)}
.check{padding:0;min-width:0}
.title{font-weight:600}
.meta{color:var(--muted);font-size:13px;margin-top:2px}
.tag{display:inline-block;font-size:12px;padding:1px 8px;border-radius:99px;border:1px solid var(--line);color:var(--muted);margin-left:6px}
.tag.late{color:var(--warn);border-color:#e0b7a8}
.empty{color:var(--muted);padding:12px 0}
.forecast{border-collapse:collapse;width:100%;font-size:14px;margin-top:6px}
.forecast td{padding:6px 4px;border-bottom:1px solid var(--line)}
.forecast td:first-child{color:var(--muted);white-space:nowrap;width:110px}
details.words{margin-top:10px}
details.words summary{cursor:pointer;color:var(--muted);font-size:13px;list-style:none}
details.words summary::-webkit-details-marker{display:none}
details.words summary:before{content:"▸ ";font-size:11px}
details[open].words summary:before{content:"▾ "}
details.words p{margin:8px 0 0;color:#4a4237;font-size:14px;line-height:1.9}
footer{margin-top:34px;display:flex;gap:10px;flex-wrap:wrap}
button{font:inherit;font-size:14px;padding:9px 16px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.note{color:var(--muted);font-size:12px;margin-top:14px}
.done-list{list-style:none;padding:0;margin:0;font-size:14px;color:var(--muted)}
.done-list li{padding:7px 0;border-bottom:1px solid var(--line)}
.done-list b{color:var(--ink);font-weight:600}
"""

_SCRIPT = """
const KEY = "vocabcurve:" + DATA.date;
let state = {};
try { state = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { state = {}; }
function save(){ try { localStorage.setItem(KEY, JSON.stringify(state)); } catch(e){} }
function paint(){
  let done = 0;
  document.querySelectorAll(".card").forEach(card => {
    const id = card.dataset.key;
    const on = !!state[id];
    card.classList.toggle("done", on);
    if (on) done++;
  });
  const n = document.querySelectorAll(".card").length;
  document.getElementById("fill").style.width = n ? (done / n * 100) + "%" : "0%";
  document.getElementById("progress").textContent = done + " / " + n + " 已完成";
}
document.querySelectorAll(".card").forEach(card => {
  card.querySelector(".check").addEventListener("click", () => {
    const id = card.dataset.key;
    state[id] = !state[id];
    save(); paint();
  });
});
document.getElementById("export").addEventListener("click", () => {
  const rows = Object.entries(state).filter(([, v]) => v).map(([k]) => {
    const [list, round] = k.split(":");
    return { list_id: list, round: Number(round) };
  });
  const blob = new Blob([JSON.stringify({ date: DATA.date, done: rows }, null, 2)], {type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "progress-" + DATA.date + ".json";
  a.click();
});
document.getElementById("reset").addEventListener("click", () => {
  if (confirm("清掉这一天在本机的勾选？")) { state = {}; save(); paint(); }
});
paint();
"""


def _card(item: Item, words: list[str] | None = None) -> str:
    late = ' <span class="tag late">补</span>' if item.status == "overdue" else ""
    later = ' <span class="tag">稍后</span>' if item.status == "later" else ""
    preview = ""
    if words:
        preview = (
            f'<details class="words"><summary>看词表（{len(words)} 词）</summary>'
            f"<p>{' · '.join(words)}</p></details>"
        )
    return (
        f'<div class="card" data-key="{item.list_id}:{item.round}">'
        f'<button class="check" aria-label="打卡"></button>'
        f"<div><div class=\"title\">{item.list_id} · {item.title}{late}{later}</div>"
        f'<div class="meta">{item.label} · {item.due:%H:%M}'
        + (f" · 后续还有 {item.pending} 轮" if item.pending else "")
        + f"</div>{preview}</div></div>"
    )


def render_html(book: Book, plan: dict, now: datetime | None = None, days: int = 14) -> str:
    now = now or datetime.now(book.tz)
    day = date.fromisoformat(plan["date"])
    groups = _groups(plan)
    total = sum(len(entries) for _, entries in groups)

    forecast_rows: list[str] = []
    for offset in range(1, days + 1):
        target = day + timedelta(days=offset)
        items = items_on(book, target)
        if not items:
            continue
        detail = "、".join(f"{x.list_id}{x.label}" for x in items[:3])
        if len(items) > 3:
            detail += f" 等 {len(items)} 项"
        forecast_rows.append(
            f"<tr><td>{cn_day(target)} {weekday(target)}</td><td>{detail}</td></tr>"
        )

    data = {
        "date": plan["date"],
        "items": [
            {"list": item.list_id, "round": item.round, "title": item.title}
            for _, items in groups
            for item in items
        ],
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    head = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>词曲线 · {day.isoformat()}</title><style>{_CSS}</style></head><body><div class=\"wrap\">"
    )
    header = (
        "<header>"
        f"<h1>{cn_day(day)}<span>{weekday(day)}</span></h1>"
        f'<p class="sub">{plan["total_due"]} 项待做'
        + (f" · {plan['total_overdue']} 篇积压" if plan["total_overdue"] else "")
        + f" · 曲线 {len(book.settings.get('intervals') or [])} 节点</p>"
        "</header>"
        '<div class="bar"><i id="fill"></i></div>'
        f'<div class="sub" id="progress">0 / {total} 已完成</div>'
    )
    def entries(items: list[Item]) -> str:
        rendered: list[str] = []
        for item in items:
            words = None
            if item.round == 0:
                words = [word.term for word in book.find(item.list_id).words[:12]]
            rendered.append(_card(item, words))
        return "".join(rendered)

    body = "".join(
        f"<h2>{title}</h2>" + entries(items) for title, items in groups
    )
    if total == 0:
        body = '<p class="empty">今天没有任务。休息，或者提前看看明天的篇目。</p>'

    completed_block = ""
    if plan.get("completed"):
        rows = plan["completed"]
        shown = rows[:3]
        extra = (
            f'<li class="more">… 另外 {len(rows) - len(shown)} 篇也已完成</li>'
            if len(rows) > len(shown)
            else ""
        )
        items = "".join(
            f"<li><b>{list_id}</b> {title} · {done_on:%m-%d} 走完曲线"
            + (f"（有 {missing} 个节点没打卡）" if missing else "")
            + "</li>"
            for list_id, title, done_on, missing in shown
        )
        completed_block = (
            f'<h2>已完成（{len(rows)} 篇，不再提醒）</h2>'
            f'<ul class="done-list">{items}{extra}</ul>'
        )

    forecast = (
        "<h2>接下来</h2>"
        '<table class="forecast">' + "".join(forecast_rows) + "</table>"
        if forecast_rows
        else ""
    )

    footer = (
        "<footer>"
        '<button class="primary" id="export">导出勾选</button>'
        '<button id="reset">清空本页勾选</button>'
        "</footer>"
        '<p class="note">勾选只存在这台设备的浏览器里；导出后用 '
        "<code>vocabcurve sync progress-*.json</code> 写回 book.json。</p>"
    )

    script = f"<script>const DATA={payload};{_SCRIPT}</script>"
    return head + header + body + completed_block + forecast + footer + script + "</div></body></html>"


def _groups(plan: dict) -> list[tuple[str, list[Item]]]:
    groups: list[tuple[str, list[Item]]] = []
    if plan.get("due_now"):
        groups.append(("现在该做", list(plan["due_now"])))
    if plan.get("later"):
        groups.append(("今天稍后", list(plan["later"])))
    if plan["overdue"]:
        groups.append(("积压，先补", list(plan["overdue"])))
    return groups
