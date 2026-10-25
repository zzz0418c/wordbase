"""用百度手写 OCR 把每篇「日期页」读出来，生成 schedule.csv（高效版：索引只建一次）。"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from .baidu_ocr import access_token, load_keys, ocr_image
from .nextdate import parse_loose, scan_dates

DB = Path.home() / "AppData" / "Roaming" / "pcsuite" / "database" / "NoteSync.db"
RES = Path.home() / "AppData" / "Roaming" / "pcsuite" / "data" / "Note" / "Resource"
PAGE_TAG = re.compile(r'<vnote-hdw[^>]*filename="([^"]+)"[^>]*>(.*?)</vnote-hdw>', re.S)


def build_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for root, _dirs, files in os.walk(RES):
        for name in files:
            if name.endswith(".webp"):
                index.setdefault(name, os.path.join(root, name))
    return index


def open_db():
    tmp = Path(tempfile.mkdtemp(prefix="baidu-"))
    for suffix in ("", "-wal", "-shm"):
        source = DB.parent / (DB.name + suffix)
        if source.exists():
            shutil.copy2(source, tmp / (DB.name + suffix))
    con = sqlite3.connect(f"file:{(tmp / DB.name).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def main(csv_path: Path = Path("schedule.csv")) -> None:
    today = date.today()
    api_key, secret_key = load_keys()
    token = access_token(api_key, secret_key)
    index = build_index()
    con = open_db()

    existing: dict[str, str] = {}
    for line in csv_path.read_text(encoding="utf-8").splitlines()[1:]:
        if "," in line:
            key, _, val = line.partition(",")
            existing[key.strip()] = val.strip()

    rows = ["title,next_date"]
    for title in existing:
        row = con.execute("SELECT contentNote FROM Note WHERE title = ?", (title,)).fetchone()
        value = None
        source = "未找到笔记"
        if row:
            pages = PAGE_TAG.findall(row["contentNote"] or "")
            if pages:
                filename, page_txt = min(pages, key=lambda p: len(p[1]))
                path = index.get(filename) or index.get(filename + ".webp")
                if path:
                    try:
                        raw = ocr_image(Path(path), token)
                        mark = re.search(r"下\s*次|下\s*一\s*次", raw)
                        if mark:
                            value = parse_loose(raw[mark.end(): mark.end() + 14], today)
                        if value is None:
                            dates = scan_dates(raw, today)
                            if dates:
                                value = dates[-1]
                        source = raw.replace("\n", " / ")[:46]
                    except Exception as exc:  # noqa: BLE001
                        source = f"OCR 失败 {str(exc)[:40]}"
                else:
                    source = "找不到图片"
        final = value.isoformat() if value else existing.get(title, "")
        rows.append(f"{title},{final}")
        print(f"{title}: {final or '未读到'}   <- {source}", flush=True)

    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"\n✓ 写入 {csv_path}", flush=True)


if __name__ == "__main__":
    main()
