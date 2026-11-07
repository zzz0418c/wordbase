"""19:00 的静默同步入口：用 pythonw.exe 运行，不会出现任何窗口。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vocabcurve.__main__ import main

try:
    main(["sync-dates", "--push"])
    main(["sync-vivo", "--push"])
except Exception:
    # 静默运行，失败也不要弹任何东西
    pass
