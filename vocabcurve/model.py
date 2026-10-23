"""数据模型：书 / 篇 / 单词 / 打卡记录，以及 book.json 的原子读写。

设计原则
--------
* 只有一份真相：book.json。其余产物（md / html / ics）都是它的投影。
* 打卡记录 ``done`` 里存 *实际完成时间*，因此「严格模式」可以随时切到
  「自适应模式」而不丢历史。
* 写盘用临时文件 + os.replace，断电不会写出半个 JSON。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 1

DEFAULT_SETTINGS: dict[str, Any] = {
    # grid=offsets：intervals 写的是「第 N 天」复习，且首学那天 = 第 1 天
    # grid=relative：intervals 是「距上一次复习多久」的间隔，适用于 5m/30m/12h 这种当天多轮
    "grid": "offsets",
    "day_base": 1,
    "intervals": ["1", "2", "4", "7", "15", "30"],
    # strict: 所有节点锚定学习日；adaptive: 按实际打卡时间顺延
    "mode": "strict",
    "timezone": "Asia/Shanghai",
    # 每天几点提醒（也是「首次学习」的锚点时刻）
    "remind_at": "07:30",
    # 起始日期（YYYY-MM-DD），首篇在这一天学
    "start": None,
    # 每天最多安排几篇新课
    "per_day": 1,
}


@dataclass
class Word:
    term: str
    sense: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"term": self.term, "sense": self.sense}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Word":
        return cls(str(raw.get("term", "")), str(raw.get("sense", "")))


@dataclass
class WordList:
    """一篇单词。``done`` 的键是轮次（"0" 表示首次学习），值是完成时间。"""

    id: str
    title: str
    start: str | None = None
    words: list[Word] = field(default_factory=list)
    done: dict[str, str] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.words)

    def finished(self, rounds: int) -> bool:
        return all(str(r) in self.done for r in range(rounds + 1))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "start": self.start,
            "words": [w.to_dict() for w in self.words],
            "done": dict(sorted(self.done.items())),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WordList":
        return cls(
            id=str(raw.get("id", "L01")),
            title=str(raw.get("title", "未命名")),
            start=raw.get("start"),
            words=[Word.from_dict(w) for w in raw.get("words", [])],
            done={str(k): str(v) for k, v in (raw.get("done") or {}).items()},
        )


@dataclass
class Book:
    settings: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    lists: list[WordList] = field(default_factory=list)

    # ---------- 派生属性 ----------

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.settings.get("timezone") or "Asia/Shanghai")

    @property
    def remind_time(self) -> time:
        raw = str(self.settings.get("remind_at") or "08:00")
        hour, _, minute = raw.partition(":")
        return time(int(hour), int(minute or 0))

    @property
    def mode(self) -> str:
        return str(self.settings.get("mode") or "strict")

    @property
    def rounds(self) -> int:
        intervals = self.settings.get("intervals") or []
        grid = str(self.settings.get("grid") or "offsets").lower()
        if grid == "offsets" and int(self.settings.get("day_base") or 1) == 1 and intervals:
            # "1,2,4,7,15,30" 里的 1 就是首学那天，不重复算一轮
            return max(0, len(intervals) - 1)
        return len(intervals)

    def find(self, list_id: str) -> WordList:
        key = list_id.strip().upper()
        for item in self.lists:
            if item.id.upper() == key:
                return item
        raise KeyError(f"找不到篇目 {list_id!r}，现有：{', '.join(i.id for i in self.lists)}")

    def index_of(self, list_id: str) -> int:
        key = list_id.strip().upper()
        for i, item in enumerate(self.lists):
            if item.id.upper() == key:
                return i
        raise KeyError(f"找不到篇目 {list_id!r}")

    @property
    def word_count(self) -> int:
        return sum(item.size for item in self.lists)

    # ---------- 序列化 ----------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": SCHEMA_VERSION,
            "settings": self.settings,
            "lists": [item.to_dict() for item in self.lists],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Book":
        settings = dict(DEFAULT_SETTINGS)
        settings.update(raw.get("settings") or {})
        return cls(
            settings=settings,
            lists=[WordList.from_dict(item) for item in raw.get("lists", [])],
        )

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".book-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return path

    @classmethod
    def load(cls, path: str | Path) -> "Book":
        path = Path(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        book = cls.from_dict(raw)
        if raw.get("version") != SCHEMA_VERSION:
            # 向前兼容：老版本只补字段，不报错
            book.settings.setdefault("mode", "strict")
        return book


def parse_day(value: str | date | datetime) -> date:
    """接受 2026-10-20 / 2026/10/20 / date / datetime。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("/", "-").replace(".", "-")
    return date.fromisoformat(text)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="minutes")
