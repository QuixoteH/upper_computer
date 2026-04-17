# =============================================================
#  config.py  —  全局配置文件（默认值 + 配置持久化工具函数）
#  ⚠  此文件只存放默认值，程序运行期间请勿直接修改此文件
#     用户配置通过 load_settings() / save_settings() 读写 settings.json
# =============================================================

import json
import os

# ── 网络默认配置 ──────────────────────────────────────────────
ESP32_HOST   = "192.168.1.101"
STREAM_PORT  = 81
TCP_PORT     = 8888
STREAM_URL   = f"http://{ESP32_HOST}:{STREAM_PORT}/stream"
TCP_HOST     = ESP32_HOST

# ── 模型配置 ──────────────────────────────────────────────────
MODEL_PATH   = "models/best.pt"   # YOLOv8x 训练权重
CONF_THRES   = 0.50
IOU_THRES    = 0.45
DEVICE       = "cpu"

# ── 性能配置 ──────────────────────────────────────────────────
# YOLOv8x 参数量是 s 的 ~7 倍，CPU 单帧推理约 600~1200ms
# SKIP_FRAMES=6 表示每 6 帧推理一次，避免队列积压卡顿
SKIP_FRAMES      = 6             # ← 原为 4，x 模型改为 6
QUEUE_SIZE       = 2
CAPTURE_INTERVAL = 10            # 同一虫种截图冷却秒数

# ── 存储配置 ──────────────────────────────────────────────────
DB_PATH       = "db/pest_monitor.db"
CAPTURE_DIR   = "captures"
LOG_PATH      = "logs/app.log"
RETAIN_DAYS   = 30
SETTINGS_FILE = "settings.json"

# ── 界面配置 ──────────────────────────────────────────────────
WIN_TITLE    = "农作物害虫识别系统"
WIN_WIDTH    = 1280
WIN_HEIGHT   = 800
VIDEO_W      = 640
VIDEO_H      = 480


# ── 配置持久化工具函数 ────────────────────────────────────────

def load_settings() -> dict:
    defaults = {
        "esp32_host":  ESP32_HOST,
        "stream_port": STREAM_PORT,
        "tcp_port":    TCP_PORT,
        "model_path":  MODEL_PATH,
        "conf_thres":  CONF_THRES,
        "retain_days": RETAIN_DAYS,
        "skip_frames": SKIP_FRAMES,
    }
    if not os.path.exists(SETTINGS_FILE):
        save_settings(defaults)
        return defaults
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (json.JSONDecodeError, OSError):
        save_settings(defaults)
        return defaults
    for k, v in defaults.items():
        stored.setdefault(k, v)
    return stored


def save_settings(data: dict):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        import logging
        logging.getLogger(__name__).error(f"写入 settings.json 失败：{e}")
