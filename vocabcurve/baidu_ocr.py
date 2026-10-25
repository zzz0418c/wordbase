"""百度智能云「手写文字识别」客户端。

拿到 API Key / Secret Key 之后，把两行写进项目根目录的 `baidu_ocr.txt`：

    API_KEY=xxxx
    SECRET_KEY=yyyy

然后 `vocabcurve sync-dates --ocr baidu` 就会用百度识别日期页，识别不了再退回本地解析。
"""

from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
OCR_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/handwriting"
CONFIG = Path("baidu_ocr.txt")


def load_keys() -> tuple[str, str]:
    api_key = os.environ.get("BAIDU_API_KEY", "")
    secret_key = os.environ.get("BAIDU_SECRET_KEY", "")
    if (not api_key or not secret_key) and CONFIG.exists():
        for line in CONFIG.read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            name, _, value = line.partition("=")
            name = name.strip().upper()
            value = value.strip()
            if name in {"API_KEY", "AK"}:
                api_key = value
            elif name in {"SECRET_KEY", "SK"}:
                secret_key = value
    if not api_key or not secret_key:
        raise RuntimeError("没有找到百度 OCR 的 API Key / Secret Key")
    return api_key, secret_key


def access_token(api_key: str, secret_key: str) -> str:
    query = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key}
    )
    with urllib.request.urlopen(f"{TOKEN_URL}?{query}", timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"取 token 失败：{data}")
    return token


def ocr_image(path: Path, token: str) -> str:
    payload = urllib.parse.urlencode(
        {"image": base64.b64encode(Path(path).read_bytes()).decode()}
    ).encode()
    request = urllib.request.Request(
        f"{OCR_URL}?access_token={urllib.parse.quote(token)}",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("error_code"):
        raise RuntimeError(f"百度 OCR 返回：{data}")
    words = [item.get("words", "") for item in data.get("words_result", [])]
    return "\n".join(words)
