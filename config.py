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
MODEL_PATH   = "models/best.pt"
CONF_THRES   = 0.50
IOU_THRES    = 0.45
DEVICE       = "cpu"

# ── 性能配置 ──────────────────────────────────────────────────
SKIP_FRAMES      = 4
QUEUE_SIZE       = 2
CAPTURE_INTERVAL = 10        # 同一虫种截图冷却秒数（新增 v3.0）

# ── 存储配置 ──────────────────────────────────────────────────
DB_PATH       = "db/pest_monitor.db"
CAPTURE_DIR   = "captures"
LOG_PATH      = "logs/app.log"
RETAIN_DAYS   = 30
SETTINGS_FILE = "settings.json"   # 运行时用户配置文件（新增 v3.0）

# ── 界面配置 ──────────────────────────────────────────────────
WIN_TITLE    = "农作物害虫识别系统"
WIN_WIDTH    = 1280
WIN_HEIGHT   = 800
VIDEO_W      = 640
VIDEO_H      = 480


# ── 配置持久化工具函数（新增 v3.0）────────────────────────────

def load_settings() -> dict:
    """
    读取 settings.json，若不存在则从 config.py 默认值生成。
    文件损坏时自动重置为默认值。
    返回包含所有运行时参数的字典。
    """
    defaults = {
        "esp32_host":  ESP32_HOST,
        "stream_port": STREAM_PORT,
        "tcp_port":    TCP_PORT,
        "model_path":  MODEL_PATH,
        "conf_thres":  CONF_THRES,
        "retain_days": RETAIN_DAYS,
    }
    if not os.path.exists(SETTINGS_FILE):
        save_settings(defaults)
        return defaults
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
    except (json.JSONDecodeError, OSError):
        # 文件损坏时重置为默认值
        save_settings(defaults)
        return defaults
    # 补全缺失键（程序版本升级后新增的键）
    for k, v in defaults.items():
        stored.setdefault(k, v)
    return stored


def save_settings(data: dict):
    """将运行时参数写入 settings.json，失败时只记录日志不抛异常"""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        import logging
        logging.getLogger(__name__).error(f"写入 settings.json 失败：{e}")