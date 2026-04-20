# =============================================================
#  core/stream_thread.py  —  MJPEG 视频流拉取线程
#  职责：连接 ESP32-CAM 视频流，逐帧读取并放入 frame_queue，
#        断线自动重连，向主线程发送连接状态信号
#  线程安全：frame_queue 由 MainWindow 创建并注入，非本模块创建
# =============================================================

import cv2
import queue
import logging
import time
from PyQt5.QtCore import QThread, pyqtSignal

import config

log = logging.getLogger(__name__)


class StreamThread(QThread):

    # ── 信号定义 ──────────────────────────────────────────────
    conn_status = pyqtSignal(bool, str)
    # bool  : True=已连接  False=已断开/连接失败
    # str   : 状态描述文字，供 AlertPanel 直接显示

    # ──────────────────────────────────────────────────────────
    #  初始化
    # ──────────────────────────────────────────────────────────
    def __init__(self, frame_queue: queue.Queue, url: str = config.STREAM_URL):
        super().__init__()
        self.frame_queue = frame_queue   # 由 MainWindow 注入，共享实例
        self.url         = url
        self._running    = False

        # 统计（可选，供调试用）
        self._frame_count   = 0
        self._last_fps_time = 0.0
        self._fps           = 0.0

    # ──────────────────────────────────────────────────────────
    #  QThread 主循环
    # ──────────────────────────────────────────────────────────
    def run(self):
        self._running = True
        log.info(f"StreamThread 启动，目标流：{self.url}")

        while self._running:
            cap = self._open_capture()

            if cap is None:
                # 打开失败，等待后重试
                self.conn_status.emit(False, f"无法连接到 {self.url}，重试中…")
                self._sleep_interruptible(500)
                continue

            self.conn_status.emit(True, f"已连接：{self.url}")
            log.info("视频流连接成功，开始读帧")
            self._frame_count   = 0
            self._last_fps_time = time.time()

            # ── 内层读帧循环 ──
            while self._running:
                ret, frame = cap.read()

                if not ret:
                    # read 失败：网络抖动或流中断，短暂等待后检测连接是否仍在
                    log.debug("cap.read() 失败，等待 50ms")
                    self.msleep(50)
                    if not cap.isOpened():
                        break   # 确认断线，跳出内层循环进行重连
                    continue

                # ── 非阻塞放入队列，队列满则丢弃旧帧（保证实时性）──
                try:
                    self.frame_queue.put_nowait(frame)
                except queue.Full:
                    pass   # 推理线程跟不上时静默丢帧，不影响流畅度

                # ── 统计 FPS（每秒更新一次）──
                self._frame_count += 1
                now = time.time()
                if now - self._last_fps_time >= 1.0:
                    self._fps           = self._frame_count / (now - self._last_fps_time)
                    self._frame_count   = 0
                    self._last_fps_time = now
                    log.debug(f"拉流帧率：{self._fps:.1f} fps")

            # ── 退出内层循环：释放资源并通知断线 ──
            cap.release()
            if self._running:
                # 非主动停止，说明是意外断线，触发重连
                log.warning("视频流意外断开，500ms 后重连")
                self.conn_status.emit(False, "视频流断开，重连中…")
                self._sleep_interruptible(500)

        log.info("StreamThread 已退出 run()")

    # ──────────────────────────────────────────────────────────
    #  辅助：打开视频流
    # ──────────────────────────────────────────────────────────
    def _open_capture(self) -> cv2.VideoCapture | None:
        """
        尝试打开 MJPEG 流，返回成功的 VideoCapture 对象，失败返回 None。
        不指定 CAP_FFMPEG，使用 OpenCV 默认后端，兼容性更好。
        """
        if not self.url:
            log.error("STREAM_URL 为空，请在 config.py 中配置正确的 IP 地址")
            return None

        log.debug(f"尝试打开视频流：{self.url}")
        cap = cv2.VideoCapture(self.url)

        # 设置读帧超时（部分 OpenCV 版本支持，不支持时静默忽略）
        try:
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC,  3000)
        except Exception:
            pass

        if not cap.isOpened():
            log.warning(f"VideoCapture 无法打开：{self.url}")
            cap.release()
            return None

        return cap

    # ──────────────────────────────────────────────────────────
    #  辅助：可中断的睡眠（每 50ms 检查一次 _running）
    # ──────────────────────────────────────────────────────────
    def _sleep_interruptible(self, total_ms: int):
        """
        替代 msleep(total_ms)。
        将长睡眠拆成 50ms 小段，使 stop() 后能快速响应，不阻塞退出。
        """
        elapsed = 0
        while self._running and elapsed < total_ms:
            self.msleep(50)
            elapsed += 50

    # ──────────────────────────────────────────────────────────
    #  停止线程（由主线程调用）
    # ──────────────────────────────────────────────────────────
    def stop(self):
        """
        安全停止线程。设置标志位后等待 run() 自然退出。
        quit() 对没有事件循环的 QThread 无实际作用，但保留以符合规范。
        """
        log.info("StreamThread stop() 被调用")
        self._running = False
        self.quit()
        if not self.wait(3000):   # 最多等 3 秒
            log.warning("StreamThread 未在 3s 内退出，强制终止")
            self.terminate()
            self.wait()

    # ──────────────────────────────────────────────────────────
    #  运行时更新流地址（SettingsDialog 保存后调用）
    # ──────────────────────────────────────────────────────────
    def update_url(self, new_url: str):
        """
        更新流地址。需先 stop() 再 start() 才生效，
        不支持热切换（ESP32-CAM 地址通常固定，此方法供设置保存后重连使用）。
        """
        log.info(f"流地址更新：{self.url} → {new_url}")
        self.url = new_url

    # ──────────────────────────────────────────────────────────
    #  属性：当前帧率（只读，供调试/UI 展示）
    # ──────────────────────────────────────────────────────────
    @property
    def fps(self) -> float:
        return round(self._fps, 1)
