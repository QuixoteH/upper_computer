# =============================================================
#  ui/alert_panel.py  —  右侧状态控制面板
#  职责：
#    1. 显示 ESP32-CAM 连接状态
#    2. 实时展示当前帧的检测虫种与置信度
#    3. 提供启动/停止/唤醒三个操作按钮
#    4. 展示今日各虫种检测统计
#    5. 显示未读告警数角标
#  宽度固定 280px，由 MainWindow 注入信号后调用对应接口方法
# =============================================================

import logging
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGroupBox, QScrollArea,
    QFrame, QSizePolicy, QSpacerItem
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui  import QColor, QPalette, QFont

log = logging.getLogger(__name__)


class AlertPanel(QWidget):
    """
    右侧固定宽度（280px）状态控制面板。
    所有对外接口均为普通方法，由 MainWindow 通过信号槽调用。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(280)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)

        # ── 各功能区块 ──────────────────────────────────────
        root.addWidget(self._build_conn_group())
        root.addWidget(self._build_detection_group())
        root.addWidget(self._build_btn_group())
        root.addWidget(self._build_stats_group())

        # 底部弹簧，防止控件被拉伸
        root.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

    # ──────────────────────────────────────────────────────────
    #  区块1：连接状态
    # ──────────────────────────────────────────────────────────
    def _build_conn_group(self) -> QGroupBox:
        box    = QGroupBox("设备连接")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # 状态指示灯 + 文字
        row = QHBoxLayout()
        self._lbl_conn_dot = QLabel("●")
        self._lbl_conn_dot.setFixedWidth(16)
        self._lbl_conn_dot.setStyleSheet("color: #888; font-size: 16px;")

        self._lbl_conn_text = QLabel("未连接")
        self._lbl_conn_text.setStyleSheet("font-weight: bold; font-size: 13px;")

        row.addWidget(self._lbl_conn_dot)
        row.addWidget(self._lbl_conn_text)
        row.addStretch()
        layout.addLayout(row)

        # 详细描述
        self._lbl_conn_msg = QLabel("等待设备上线…")
        self._lbl_conn_msg.setWordWrap(True)
        self._lbl_conn_msg.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self._lbl_conn_msg)

        return box

    # ──────────────────────────────────────────────────────────
    #  区块2：实时检测结果
    # ──────────────────────────────────────────────────────────
    def _build_detection_group(self) -> QGroupBox:
        box    = QGroupBox("当前检测")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 主要虫种（字体最大）
        self._lbl_pest_name = QLabel("—")
        self._lbl_pest_name.setAlignment(Qt.AlignCenter)
        self._lbl_pest_name.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #c05c00;"
        )
        layout.addWidget(self._lbl_pest_name)

        # 置信度
        row_conf = QHBoxLayout()
        row_conf.addWidget(QLabel("置信度："))
        self._lbl_confidence = QLabel("—")
        self._lbl_confidence.setStyleSheet("font-weight: bold; color: #2e7d32;")
        row_conf.addWidget(self._lbl_confidence)
        row_conf.addStretch()
        layout.addLayout(row_conf)

        # 数量
        row_cnt = QHBoxLayout()
        row_cnt.addWidget(QLabel("本帧数量："))
        self._lbl_count = QLabel("—")
        self._lbl_count.setStyleSheet("font-weight: bold;")
        row_cnt.addWidget(self._lbl_count)
        row_cnt.addStretch()
        layout.addLayout(row_cnt)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #ddd;")
        layout.addWidget(line)

        # 无检测时的提示
        self._lbl_no_det = QLabel("未检测到害虫 ✓")
        self._lbl_no_det.setAlignment(Qt.AlignCenter)
        self._lbl_no_det.setStyleSheet("color: #2e7d32; font-size: 12px;")
        layout.addWidget(self._lbl_no_det)

        return box

    # ──────────────────────────────────────────────────────────
    #  区块3：操作按钮
    # ──────────────────────────────────────────────────────────
    def _build_btn_group(self) -> QGroupBox:
        box    = QGroupBox("监测控制")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 启动 / 停止（一行两列）
        row1 = QHBoxLayout()
        self.btn_start = QPushButton("▶ 启动监测")
        self.btn_start.setFixedHeight(32)
        self.btn_start.setStyleSheet(
            "QPushButton { background:#2e7d32; color:white; border-radius:4px; font-weight:bold; }"
            "QPushButton:hover { background:#388e3c; }"
            "QPushButton:disabled { background:#aaa; }"
        )

        self.btn_stop = QPushButton("■ 停止")
        self.btn_stop.setFixedHeight(32)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "QPushButton { background:#c62828; color:white; border-radius:4px; font-weight:bold; }"
            "QPushButton:hover { background:#d32f2f; }"
            "QPushButton:disabled { background:#aaa; }"
        )

        row1.addWidget(self.btn_start)
        row1.addWidget(self.btn_stop)
        layout.addLayout(row1)

        # 唤醒按钮（整行）
        self.btn_wake = QPushButton("⚡ 发送唤醒指令")
        self.btn_wake.setFixedHeight(30)
        self.btn_wake.setToolTip("通过 TCP:8888 唤醒 ESP32-CAM 开始推流")
        self.btn_wake.setStyleSheet(
            "QPushButton { background:#1a5fa8; color:white; border-radius:4px; }"
            "QPushButton:hover { background:#1565c0; }"
            "QPushButton:disabled { background:#aaa; }"
        )
        layout.addWidget(self.btn_wake)

        return box

    # ──────────────────────────────────────────────────────────
    #  区块4：今日统计
    # ──────────────────────────────────────────────────────────
    def _build_stats_group(self) -> QGroupBox:
        box    = QGroupBox("今日统计")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # 未读告警角标
        alert_row = QHBoxLayout()
        alert_row.addWidget(QLabel("未读告警："))
        self._lbl_alert_badge = QLabel("0")
        self._lbl_alert_badge.setStyleSheet(
            "background: #c62828; color: white; border-radius: 8px;"
            "padding: 1px 6px; font-weight: bold; font-size: 11px;"
        )
        alert_row.addWidget(self._lbl_alert_badge)
        alert_row.addStretch()
        layout.addLayout(alert_row)

        # 统计列表：可滚动
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setFixedHeight(120)

        self._stats_container = QWidget()
        self._stats_layout    = QVBoxLayout(self._stats_container)
        self._stats_layout.setContentsMargins(0, 0, 0, 0)
        self._stats_layout.setSpacing(2)
        self._stats_layout.addWidget(QLabel("暂无数据"))

        scroll.setWidget(self._stats_container)
        layout.addWidget(scroll)

        return box

    # ──────────────────────────────────────────────────────────
    #  对外接口：更新连接状态（由 MainWindow._on_conn_status 调用）
    # ──────────────────────────────────────────────────────────
    def update_conn_status(self, online: bool, msg: str):
        if online:
            self._lbl_conn_dot.setStyleSheet(
                "color: #2e7d32; font-size: 16px;"
            )
            self._lbl_conn_text.setText("已连接")
            self._lbl_conn_text.setStyleSheet(
                "font-weight: bold; font-size: 13px; color: #2e7d32;"
            )
        else:
            self._lbl_conn_dot.setStyleSheet(
                "color: #c62828; font-size: 16px;"
            )
            self._lbl_conn_text.setText("未连接")
            self._lbl_conn_text.setStyleSheet(
                "font-weight: bold; font-size: 13px; color: #c62828;"
            )
        # 截断过长的描述文字（防止撑宽面板）
        short_msg = msg if len(msg) <= 36 else msg[:33] + "…"
        self._lbl_conn_msg.setText(short_msg)

    # ──────────────────────────────────────────────────────────
    #  对外接口：更新实时检测结果（由 result_ready 信号触发）
    # ──────────────────────────────────────────────────────────
    def update_detection(self, frame, detections: list):
        """
        根据当前帧的检测结果更新面板显示。
        detections 格式：[{"class_name": str, "confidence": float, ...}, ...]
        """
        if not detections:
            # 无检测目标
            self._lbl_pest_name.setText("—")
            self._lbl_confidence.setText("—")
            self._lbl_count.setText("—")
            self._lbl_no_det.setVisible(True)
            self._lbl_pest_name.setStyleSheet(
                "font-size: 18px; font-weight: bold; color: #888;"
            )
            return

        self._lbl_no_det.setVisible(False)

        # 取置信度最高的一条作为主显示
        top = max(detections, key=lambda d: d["confidence"])

        self._lbl_pest_name.setText(top["class_name"])
        self._lbl_pest_name.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #c05c00;"
        )
        self._lbl_confidence.setText(f"{top['confidence']:.1%}")
        self._lbl_count.setText(f"{len(detections)} 个")

        # 置信度颜色：高→绿，中→橙，低→红
        conf = top["confidence"]
        if conf >= 0.75:
            color = "#2e7d32"
        elif conf >= 0.55:
            color = "#c05c00"
        else:
            color = "#c62828"
        self._lbl_confidence.setStyleSheet(
            f"font-weight: bold; color: {color};"
        )

    # ──────────────────────────────────────────────────────────
    #  对外接口：刷新今日统计（由 MainWindow 定时器每 10s 触发）
    # ──────────────────────────────────────────────────────────
    def update_statistics(self, rows: list):
        """
        rows: list[sqlite3.Row]，每行包含 pest_class / times / total_count
        """
        # 清空旧内容
        while self._stats_layout.count():
            item = self._stats_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not rows:
            self._stats_layout.addWidget(QLabel("今日暂无检测记录"))
            self._lbl_alert_badge.setText("0")
            return

        total_alerts = 0
        for row in rows:
            pest   = row["pest_class"]
            times  = row["times"]
            total  = row["total_count"]
            total_alerts += times

            lbl = QLabel(f"• {pest}：{times} 次（共 {total} 只）")
            lbl.setStyleSheet("font-size: 11px; color: #333;")
            lbl.setWordWrap(True)
            self._stats_layout.addWidget(lbl)

        # 更新未读告警角标（用今日检测次数近似）
        self._lbl_alert_badge.setText(str(total_alerts))
        badge_color = "#c62828" if total_alerts > 0 else "#2e7d32"
        self._lbl_alert_badge.setStyleSheet(
            f"background: {badge_color}; color: white; border-radius: 8px;"
            "padding: 1px 6px; font-weight: bold; font-size: 11px;"
        )

    # ──────────────────────────────────────────────────────────
    #  对外接口：同步按钮状态（由 MainWindow._update_btn_state 调用）
    # ──────────────────────────────────────────────────────────
    def set_monitoring_state(self, monitoring: bool):
        """
        监测运行中：启动按钮禁用，停止按钮启用；反之亦然。
        """
        self.btn_start.setEnabled(not monitoring)
        self.btn_stop.setEnabled(monitoring)