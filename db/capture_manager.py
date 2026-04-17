# =============================================================
#  core/capture_manager.py  —  检测截图管理器
#  职责：保存标注帧为 JPEG 文件，定期清理超期截图，返回保存路径
#  命名格式：captures/YYYYMMDD_HHMMSS_classname.jpg
#  线程说明：由 DetectThread 调用，内部加锁保证文件操作安全
# =============================================================

import cv2
import os
import re
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

import config

log = logging.getLogger(__name__)

# JPEG 保存质量（0~100，85 是清晰度与文件大小的平衡点）
_JPEG_QUALITY = 85


class CaptureManager:

    def __init__(self,
                 save_dir:    str = config.CAPTURE_DIR,
                 retain_days: int = config.RETAIN_DAYS):
        self.save_dir    = save_dir
        self.retain_days = retain_days
        self._lock       = threading.Lock()   # 保护目录清理和写文件

        # 确保目录存在
        os.makedirs(self.save_dir, exist_ok=True)
        log.info(f"CaptureManager 初始化：目录={self.save_dir}  "
                 f"保留={self.retain_days}天")

        # 启动时清理一次超期截图（防止上次运行遗留）
        self.cleanup_old()

        # 记录上次清理时间，后续每隔一天自动清理一次
        self._last_cleanup_date: str = datetime.now().strftime("%Y-%m-%d")

    # ──────────────────────────────────────────────────────────
    #  保存截图（DetectThread 调用）
    # ──────────────────────────────────────────────────────────
    def save(self, frame, class_name: Optional[str] = None) -> str:
        """
        将标注帧保存为 JPEG 文件。
        参数：
            frame      : numpy BGR 数组（results.plot() 的输出）
            class_name : 检测到的害虫类名，写入文件名便于快速浏览
        返回：
            保存的相对路径，如 'captures/20260414_185530_aphid.jpg'
        异常：
            保存失败时抛出 IOError
        """
        # 每天自动触发一次清理（不影响主流程）
        self._daily_cleanup_check()

        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = self._sanitize(class_name) if class_name else "unknown"
        filename = f"{ts}_{safe}.jpg"
        path     = os.path.join(self.save_dir, filename)

        with self._lock:
            success = cv2.imwrite(
                path,
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY]
            )

        if not success:
            raise IOError(f"cv2.imwrite 保存失败：{path}")

        log.debug(f"截图已保存：{path}")
        return path

    # ──────────────────────────────────────────────────────────
    #  查询：截图数量和总占用（供设置界面展示磁盘用量）
    # ──────────────────────────────────────────────────────────
    def get_stats(self) -> dict:
        """
        返回截图目录的统计信息。
        {
          "count":      int,    # 文件总数
          "total_mb":   float,  # 总占用 MB
          "oldest":     str,    # 最早文件时间戳（无则为 ''）
        }
        """
        files = self._list_jpg_files()
        if not files:
            return {"count": 0, "total_mb": 0.0, "oldest": ""}

        total_bytes = sum(os.path.getsize(f) for f in files)
        mtimes      = [os.path.getmtime(f) for f in files]
        oldest_ts   = datetime.fromtimestamp(min(mtimes)).strftime("%Y-%m-%d %H:%M:%S")

        return {
            "count":    len(files),
            "total_mb": round(total_bytes / 1024 / 1024, 2),
            "oldest":   oldest_ts,
        }

    # ──────────────────────────────────────────────────────────
    #  清理：删除超期截图文件（每天触发一次 + 启动时触发一次）
    # ──────────────────────────────────────────────────────────
    def cleanup_old(self) -> int:
        """
        删除 mtime 超过 retain_days 天的 jpg 文件。
        返回：删除的文件数量
        """
        cutoff   = datetime.now() - timedelta(days=self.retain_days)
        deleted  = 0
        files    = self._list_jpg_files()

        with self._lock:
            for fpath in files:
                try:
                    if datetime.fromtimestamp(os.path.getmtime(fpath)) < cutoff:
                        os.remove(fpath)
                        deleted += 1
                        log.debug(f"已删除超期截图：{fpath}")
                except OSError as e:
                    log.warning(f"删除截图失败：{fpath}  原因：{e}")

        if deleted:
            log.info(f"清理超期截图：删除 {deleted} 个文件（cutoff={cutoff.date()}）")
        return deleted

    # ──────────────────────────────────────────────────────────
    #  内部辅助
    # ──────────────────────────────────────────────────────────
    def _daily_cleanup_check(self):
        """每天只触发一次清理，避免每次 save() 都遍历目录"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_cleanup_date:
            self._last_cleanup_date = today
            # 在后台线程中清理，不阻塞推理循环
            t = threading.Thread(target=self.cleanup_old, daemon=True)
            t.start()

    def _list_jpg_files(self) -> list[str]:
        """返回 save_dir 下所有 .jpg 文件的完整路径列表"""
        try:
            return [
                os.path.join(self.save_dir, f)
                for f in os.listdir(self.save_dir)
                if f.lower().endswith(".jpg")
            ]
        except OSError as e:
            log.error(f"无法读取截图目录：{e}")
            return []

    @staticmethod
    def _sanitize(name: str) -> str:
        """
        将害虫类名转为合法文件名（去除特殊字符，限制长度）。
        例："rice borer" → "rice_borer"
            "蚜虫/害虫"  → "___"
        """
        safe = re.sub(r'[\\/:*?"<>|\s]', "_", name)
        return safe[:32] if safe else "unknown"