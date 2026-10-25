"""把指定篇的第一页（哪怕很长）整页跑百度 OCR，找「下次」日期。"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

from .baidu_ocr import access_token, load_keys, ocr_image
from .baidu_sync import PAGE_TAG, build_index, open_db
from .nextdate import parse_loose, scan_dates


def main(titles: list[str]) -> None:
    today = date.today()
    api_key, secret_key = load_keys()
    token = access_token(api_key, secret_key)
    index = build_index()
    con = open_db()

    for title in titles:
        row = con.execute("SELECT contentNote FROM Note WHERE title = ?", (title,)).fetchone()
        print(f"===== {title}", flush=True)
        if not row:
            print("  没这条笔记", flush=True)
            continue
        pages = PAGE_TAG.findall(row["contentNote"] or "")
        if not pages:
            print("  没有页", flush=True)
            continue
        filename, _text = pages[0]
        path = index.get(filename) or index.get(filename + ".webp")
        if not path:
            print("  首图未同步", flush=True)
            continue
        raw = ocr_image(Path(path), token)
        print("  OCR首行:", raw.replace("\n", " / ")[:120], flush=True)
        mark = re.search(r"下\s*次|下\s*一\s*次", raw)
        value = parse_loose(raw[mark.end(): mark.end() + 14], today) if mark else None
        if value is None:
            dates = scan_dates(raw, today)
            value = max(dates) if dates else None
        print(f"  => {value}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
