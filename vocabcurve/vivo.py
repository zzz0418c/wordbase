"""从 vivo 办公套件同步下来的 NoteSync.db 里读「原子笔记」。

为什么需要它：原子笔记没有对外接口，但 PC 上的 vivo 办公套件会把笔记实时同步到
``%APPDATA%\\pcsuite\\database\\NoteSync.db``。只读打开这个库，就能直接拿到
笔记本、标题和正文——**平板那边不用任何操作**。

注意：图片笔记（type=100）的正文只是 OCR 文本，噪声很大，所以默认只用它做
"篇名"，词条仍以你在笔记里看到的为准。
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .model import Word, WordList
from .parse import parse_entry

DB_NAME = "NoteSync.db"
_TAG_RE = re.compile(r"<[^>]+>")
_PAGES_RE = re.compile(r'<vnote-hdw[^>]*>(.*?)</vnote-hdw>', re.S)
_PAGE_RE = re.compile(r'<vnote-hdw[^>]*page="1"[^>]*>(.*?)</vnote-hdw>', re.S)


def default_db_path() -> Path:
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "pcsuite" / "database" / DB_NAME,
        Path.home() / "AppData" / "Roaming" / "pcsuite" / "database" / DB_NAME,
        Path.home() / "Library" / "Application Support" / "pcsuite" / "database" / DB_NAME,
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        "没找到 vivo 办公套件的 NoteSync.db。先装「vivo 办公套件」并用同一个账号登录、"
        "打开一次原子笔记让它同步；或者手动导出文本用 `vocabcurve import`。"
    )


@dataclass
class VivoNote:
    id: int
    title: str
    notebook: str
    kind: int
    text: str
    first_page: str = ""
    pages: list[str] = field(default_factory=list)

    @property
    def is_image(self) -> bool:
        return self.kind == 100


def _snapshot(db: Path) -> Path:
    """连 -wal/-shm 一起复制，避免读到半个事务、也不锁住正在用的库。"""
    tmp = Path(tempfile.mkdtemp(prefix="vivo-notes-"))
    shutil.copy2(db, tmp / DB_NAME)
    for suffix in ("-wal", "-shm"):
        side = db.with_name(DB_NAME + suffix)
        if side.exists():
            shutil.copy2(side, tmp / (DB_NAME + suffix))
    return tmp


def load_notes(db: Path | None = None) -> list[VivoNote]:
    db = db or default_db_path()
    tmp = _snapshot(db)
    try:
        con = sqlite3.connect(f"file:{(tmp / DB_NAME).as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        books = {
            row["guid"]: (row["nameNew"] or row["name"] or "")
            for row in con.execute("SELECT guid, name, nameNew FROM NoteBook")
        }
        rows = con.execute(
            """
            SELECT id, title, noteBookGuid, type, contentNote, updateTime
            FROM Note WHERE deleted >= 0
            ORDER BY updateTime DESC
            """
        ).fetchall()
        notes: list[VivoNote] = []
        for row in rows:
            raw = row["contentNote"] or ""
            text = _TAG_RE.sub("\n", raw)
            pages = _PAGE_RE.findall(raw)
            first_page = pages[0].strip() if pages else text.strip().split("\n")[0]
            notes.append(
                VivoNote(
                    id=int(row["id"]),
                    title=(row["title"] or "").strip(),
                    notebook=books.get(row["noteBookGuid"], ""),
                    kind=int(row["type"] or 0),
                    text=text,
                    first_page=first_page,
                    pages=[page.strip() for page in _PAGES_RE.findall(raw)],
                )
            )
        return notes
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)


def notebooks(notes: list[VivoNote]) -> list[tuple[str, int]]:
    counter: dict[str, int] = {}
    for note in notes:
        if not note.title:
            continue
        key = note.notebook or "(未分类)"
        counter[key] = counter.get(key, 0) + 1
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))


def _natural_key(text: str) -> list:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


def select(
    notes: list[VivoNote], notebook: str | None = None, pattern: str | None = None
) -> list[VivoNote]:
    picked = notes
    if notebook:
        picked = [n for n in picked if notebook in n.notebook]
    if pattern:
        regex = re.compile(pattern)
        picked = [n for n in picked if regex.search(n.title)]
    picked = [n for n in picked if n.title]
    return sorted(picked, key=lambda n: _natural_key(n.title))


def to_lists(picked: list[VivoNote], clean_only: bool = False) -> list[WordList]:
    """每条笔记 = 一篇。图片笔记的 OCR 文本噪声太大，少于 3 条干净词条就当没有词表。"""
    lists: list[WordList] = []
    for note in picked:
        words: list[Word] = []
        for line in note.text.split("\n"):
            word = parse_entry(line)
            if word is None:
                continue
            if word.sense and len(word.term) <= 32:
                words.append(word)
        if len(words) < 3:
            words = []
        if clean_only and not words:
            continue
        lists.append(
            WordList(
                id=f"L{len(lists) + 1:02d}",
                title=note.title,
                words=words,
            )
        )
    return lists
