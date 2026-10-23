"""看第 8/20/21 篇第一页的完整文本，找圈号和手写的下次日期。"""
from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

SRC = Path.home() / "AppData" / "Roaming" / "pcsuite" / "database" / "NoteSync.db"
TMP = Path(tempfile.mkdtemp(prefix="probe-"))
for name in ("NoteSync.db", "NoteSync.db-wal", "NoteSync.db-shm"):
    if (SRC.parent / name).exists():
        shutil.copy2(SRC.parent / name, TMP / name)

con = sqlite3.connect(f"file:{(TMP / 'NoteSync.db').as_posix()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
PAGE = re.compile(r'<vnote-hdw page="1"[^>]*>(.*?)</vnote-hdw>', re.S)

for title in ("雅思词汇真经08", "雅思词汇真经20", "雅思词汇真经21", "雅思词汇真经01"):
    row = con.execute("SELECT contentNote FROM Note WHERE title = ?", (title,)).fetchone()
    match = PAGE.search(row["contentNote"] or "")
    text = match.group(1) if match else "(no page1)"
    print(f"===== {title} ({len(text)} chars)")
    print(text[:700].replace("\n", " "))
    print()
