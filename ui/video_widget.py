# =============================================================
#  ui/video_widget.py  —  实时视频显示控件
#  职责：
#    1. 接收 DetectThread 发来的标注帧（BGR numpy）
#    2. 完成 BGR→RGB 转换后用 QLabel 渲染，保持宽高比缩放
#    3. 叠加显示当前帧的检测统计信息（帧率 / 检测数）
#    4. 无视频流时显示占位画面
#  ⚠ BGR→RGB 转换必须在此处完成，DetectThread 只传原始 BGR 帧
# =============================================================

import time
import logging
import numpy as np
import cv2

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore    import Qt, QSize
from PyQt5.QtGui     import QImage, QPixmap, QPainter, QColor, QFont

import config

log = logging.getLogger(__name__)


class VideoWidget(QWidget):
    """
    实时视频显示控件。
    直接作为子控件嵌入 MainWindow 的左侧区域。
    """

    # 占位文字（无流/停止监测时显示）
    _IDLE_TEXT  = "等待视频流…\n请确认 ESP32-CAM 已上电并连接到同一网络"
    # OSD 字体颜色（On-Screen Display）
    _OSD_COLOR  = QColor(255, 255, 0)     # 黄色，在暗背景上清晰可读
    _OSD_BG     = QColor(0, 0, 0, 140)    # 半透明黑底

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(config.VIDEO_W, config.VIDEO_H)

        # ── 主显示 Label ──────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._label.setStyleSheet("background-color: #1a1a1a;")
        layout.addWidget(self._label)

        # ── 帧率统计 ──────────────────────────────────────────
        self._frame_count   = 0
        self._fps           = 0.0
        self._last_fps_time = time.time()

        # ── OSD 信息（叠加在画面上） ──────────────────────────
        self._last_det_count = 0   # 上一帧的检测目标数量
        self._show_osd       = True

        # 初始显示占位画面
        self.show_idle()

    # ──────────────────────────────────────────────────────────
    #  主接口：更新视频帧（由 DetectThread.result_ready 信号触发）
    # ──────────────────────────────────────────────────────────
    def update_frame(self, frame: np.ndarray, detections: list):
        """
        接收标注帧并显示。
        参数：
            frame      : BGR numpy 数组（results.plot() 输出）
            detections : 检测结果列表，用于 OSD 统计显示
        """
        if frame is None or frame.size == 0:
            log.debug("update_frame 收到空帧，跳过")
            return

        self._last_det_count = len(detections)
        self._update_fps()

        # ── BGR → RGB（关键转换，OpenCV 是 BGR，QImage 需要 RGB）
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w

        qimg = QImage(
            rgb.data,
            w, h,
            bytes_per_line,
            QImage.Format_RGB888
        )

        # ── 按 Label 大小缩放，保持宽高比，抗锯齿平滑
        pixmap = QPixmap.fromImage(qimg).scaled(
            self._label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        # ── 叠加 OSD 信息
        if self._show_osd:
            pixmap = self._draw_osd(pixmap)

        self._label.setPixmap(pixmap)

    # ──────────────────────────────────────────────────────────
    #  占位画面（停止监测 / 等待连接时显示）
    # ──────────────────────────────────────────────────────────
    def show_idle(self):
        """
        清除视频画面，显示"等待视频流"占位文字。
        由 MainWindow.stop_monitoring() 调用。
        """
        self._fps            = 0.0
        self._frame_count    = 0
        self._last_fps_time  = time.time()
        self._last_det_count = 0

        self._label.setPixmap(QPixmap())   # 清空图像
        self._label.setText(self._IDLE_TEXT)
        self._label.setStyleSheet(
            "background-color: #1a1a1a;"
            "color: #888888;"
            "font-size: 14px;"
        )

    # ──────────────────────────────────────────────────────────
    #  OSD：帧率 + 检测数叠加（QPainter 绘制在 Pixmap 上）
    # ──────────────────────────────────────────────────────────
    def _draw_osd(self, pixmap: QPixmap) -> QPixmap:
        """
        在 pixmap 左上角绘制半透明黑底文字信息：
          FPS: xx.x  |  检测: x 个目标
        返回带 OSD 的新 pixmap（不修改原始帧数据）。
        """
        text = (
            f"FPS: {self._fps:.1f}    "
            f"检测: {self._last_det_count} 个目标"
        )

        # 复制一份再绘制，不污染原 pixmap
        result = pixmap.copy()
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)

        font = QFont("Consolas", 11)
        font.setBold(True)
        painter.setFont(font)

        fm      = painter.fontMetrics()
        text_w  = fm.horizontalAdvance(text)
        text_h  = fm.height()
        padding = 6

        # 绘制半透明黑底矩形
        painter.fillRect(
            8, 8,
            text_w + padding * 2,
            text_h + padding,
            self._OSD_BG
        )

        # 绘制文字
        painter.setPen(self._OSD_COLOR)
        painter.drawText(8 + padding, 8 + text_h, text)
        painter.end()

        return result

    # ──────────────────────────────────────────────────────────
    #  帧率统计（每秒更新一次）
    # ──────────────────────────────────────────────────────────
    def _update_fps(self):
        self._frame_count += 1
        now = time.time()
        elapsed = now - self._last_fps_time
        if elapsed >= 1.0:
            self._fps           = self._frame_count / elapsed
            self._frame_count   = 0
            self._last_fps_time = now

    # ──────────────────────────────────────────────────────────
    #  OSD 开关（可由菜单/快捷键控制，预留接口）
    # ──────────────────────────────────────────────────────────
    def toggle_osd(self):
        """切换 OSD 信息显示/隐藏"""
        self._show_osd = not self._show_osd
        log.debug(f"OSD 已{'开启' if self._show_osd else '关闭'}")

    # ──────────────────────────────────────────────────────────
    #  Qt 尺寸建议
    # ──────────────────────────────────────────────────────────
    def sizeHint(self) -> QSize:
        return QSize(config.VIDEO_W, config.VIDEO_H)