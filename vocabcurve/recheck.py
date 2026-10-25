"""只重读指定的几篇（用百度 OCR），打印每页的识别结果，方便人工核对。"""

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
            print("  没找到这条笔记", flush=True)
            continue
        pages = PAGE_TAG.findall(row["contentNote"] or "")
        print(f"  共 {len(pages)} 页", flush=True)
        for filename, page_txt in pages:
            path = index.get(filename) or index.get(filename + ".webp")
            if not path:
                print(f"  [{filename}] 图片未同步", flush=True)
                continue
            if len(page_txt) > 200:
                continue  # 单词正文页，跳过
            try:
                raw = ocr_image(Path(path), token)
            except Exception as exc:  # noqa: BLE001
                print(f"  [{filename}] OCR 失败 {exc}", flush=True)
                continue
            mark = re.search(r"下\s*次|下\s*一\s*次", raw)
            value = parse_loose(raw[mark.end(): mark.end() + 14], today) if mark else None
            if value is None:
                dates = scan_dates(raw, today)
                value = dates[-1] if dates else None
            print(f"  OCR: {raw.replace(chr(10), ' / ')[:90]}", flush=True)
            print(f"  => {value}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
