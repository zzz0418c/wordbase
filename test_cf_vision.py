import base64
import json
import subprocess
import ssl
import urllib.request
from pathlib import Path

def oauth_token() -> str:
    cfg = Path.home() / "AppData/Roaming/xdg.config/.wrangler/config/default.toml"
    for line in cfg.read_text(encoding="utf-8").splitlines():
        if line.startswith("oauth_token"):
            return line.split('"')[1]
    raise SystemExit("no token")

ACCOUNT = "93e62381deded528f64d2de8fe312cc4"
MODEL = "@cf/llava-hf/llava-1.5-7b-hf"
image = Path("u12.webp").read_bytes()

body = json.dumps({
    "image": list(image[:600000]),
    "prompt": "Transcribe the handwritten text in this image exactly. It contains dates like 26.10.21 and a line starting with 下次. Output only the text.",
    "max_tokens": 120,
}).encode()

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

req = urllib.request.Request(
    f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/run/{MODEL}",
    data=body,
    headers={"Authorization": f"Bearer {oauth_token()}", "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, context=ctx, timeout=120) as r:
        print(r.read().decode()[:800])
except Exception as exc:
    print("ERR", exc)
    if hasattr(exc, "read"):
        print(exc.read().decode()[:800])
