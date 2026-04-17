# =============================================================
#  main.py  —  程序入口
#  ⚠ torch 必须在 PyQt5 之前预加载，否则 Windows 下 c10.dll 初始化失败
# =============================================================

# ── 必须是文件第一行有效 import ────────────────────────────────
import os
import platform
if platform.system() == "Windows":
    import ctypes
    from importlib.util import find_spec
    try:
        spec = find_spec("torch")
        if spec and spec.origin:
            dll_path = os.path.join(os.path.dirname(spec.origin), "lib", "c10.dll")
            if os.path.exists(dll_path):
                ctypes.CDLL(os.path.normpath(dll_path))
    except Exception:
        pass
# ─────────────────────────────────────────────────────────────

import sys
import logging
from PyQt5.QtWidgets import QApplication
from ui.main_window import MainWindow
import config

os.makedirs(os.path.dirname(config.LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName(config.WIN_TITLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())