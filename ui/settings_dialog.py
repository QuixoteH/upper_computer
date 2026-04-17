# =============================================================
#  ui/settings_dialog.py  —  高级设置对话框
#  职责：
#    1. 展示并允许修改所有高级运行参数（端口/模型/阈值等）
#    2. 保存时写入 settings.json 并校验参数合法性
#    3. 提供 get_host() / get_stream_url() / get_tcp_port()
#       供 MainWindow._open_settings() 获取新值后更新模块
#  注意：IP 地址的快速修改由主窗口工具栏完成，
#        本对话框负责不常修改的高级参数，两者互不干扰
# =============================================================

import os
import logging
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QDoubleSpinBox,
    QSpinBox, QFileDialog, QDialogButtonBox,
    QGroupBox, QMessageBox, QTabWidget, QWidget
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui  import QIntValidator

from config import load_settings, save_settings
import config

log = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """
    高级设置对话框（模态）。
    用法：
        dlg = SettingsDialog(parent)
        if dlg.exec_():
            host = dlg.get_host()
            url  = dlg.get_stream_url()
            port = dlg.get_tcp_port()
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("连接与模型设置")
        self.setMinimumWidth(420)
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint
        )

        # 读取当前配置
        self._s = load_settings()

        root = QVBoxLayout(self)
        root.setSpacing(10)

        # Tab 分组：连接设置 / 模型设置 / 存储设置
        tabs = QTabWidget()
        tabs.addTab(self._build_conn_tab(),    "📡  连接")
        tabs.addTab(self._build_model_tab(),   "🤖  模型")
        tabs.addTab(self._build_storage_tab(), "💾  存储")
        root.addWidget(tabs)

        # 提示文字
        hint = QLabel("💡 IP 地址的快速修改请使用主界面工具栏的输入框")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # 确定 / 取消 / 恢复默认
        btn_box = QDialogButtonBox()
        self._btn_ok      = btn_box.addButton("保存", QDialogButtonBox.AcceptRole)
        self._btn_cancel  = btn_box.addButton("取消", QDialogButtonBox.RejectRole)
        self._btn_default = btn_box.addButton("恢复默认", QDialogButtonBox.ResetRole)
        self._btn_ok.setDefault(True)

        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        self._btn_default.clicked.connect(self._restore_defaults)
        root.addWidget(btn_box)

    # ──────────────────────────────────────────────────────────
    #  Tab 1：连接设置
    # ──────────────────────────────────────────────────────────
    def _build_conn_tab(self) -> QWidget:
        tab    = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)

        box    = QGroupBox("ESP32-CAM 连接参数")
        form   = QFormLayout(box)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setSpacing(10)

        # ESP32-CAM IP
        self._edit_host = QLineEdit(self._s["esp32_host"])
        self._edit_host.setPlaceholderText("例：192.168.1.101")
        self._edit_host.setToolTip(
            "ESP32-CAM 的局域网 IP 地址\n"
            "快速修改也可使用主界面顶部工具栏的输入框"
        )
        form.addRow("ESP32-CAM IP：", self._edit_host)

        # MJPEG 流端口
        self._spin_stream_port = QSpinBox()
        self._spin_stream_port.setRange(1, 65535)
        self._spin_stream_port.setValue(self._s["stream_port"])
        self._spin_stream_port.setToolTip("MJPEG 视频流端口，固定 81，一般无需修改")
        form.addRow("视频流端口：", self._spin_stream_port)

        # TCP 控制端口
        self._spin_tcp_port = QSpinBox()
        self._spin_tcp_port.setRange(1, 65535)
        self._spin_tcp_port.setValue(self._s["tcp_port"])
        self._spin_tcp_port.setToolTip("TCP 唤醒指令端口，固定 8888，一般无需修改")
        form.addRow("TCP 控制端口：", self._spin_tcp_port)

        # 预览当前完整流地址（只读）
        self._lbl_preview = QLabel(self._build_url_preview())
        self._lbl_preview.setStyleSheet(
            "color: #1a5fa8; font-family: Consolas, monospace; font-size: 11px;"
        )
        self._lbl_preview.setWordWrap(True)
        form.addRow("流地址预览：", self._lbl_preview)

        # 任一字段改变时刷新预览
        self._edit_host.textChanged.connect(self._refresh_url_preview)
        self._spin_stream_port.valueChanged.connect(self._refresh_url_preview)

        layout.addWidget(box)
        layout.addStretch()
        return tab

    # ──────────────────────────────────────────────────────────
    #  Tab 2：模型设置
    # ──────────────────────────────────────────────────────────
    def _build_model_tab(self) -> QWidget:
        tab    = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)

        box  = QGroupBox("YOLOv8 推理参数")
        form = QFormLayout(box)
        form.setSpacing(10)

        # 模型权重路径
        path_row = QHBoxLayout()
        self._edit_model = QLineEdit(self._s["model_path"])
        self._edit_model.setToolTip("YOLOv8s 权重文件路径（best.pt）")
        btn_browse = QPushButton("浏览…")
        btn_browse.setFixedWidth(60)
        btn_browse.clicked.connect(self._browse_model)
        path_row.addWidget(self._edit_model)
        path_row.addWidget(btn_browse)
        form.addRow("模型路径：", path_row)

        # 置信度阈值
        self._spin_conf = QDoubleSpinBox()
        self._spin_conf.setRange(0.10, 0.99)
        self._spin_conf.setSingleStep(0.05)
        self._spin_conf.setDecimals(2)
        self._spin_conf.setValue(self._s["conf_thres"])
        self._spin_conf.setToolTip(
            "检测置信度阈值（0.10~0.99）\n"
            "值越高误检越少，但可能漏检；建议 0.50~0.60"
        )
        form.addRow("置信度阈值：", self._spin_conf)

        # 跳帧间隔
        self._spin_skip = QSpinBox()
        self._spin_skip.setRange(1, 30)
        self._spin_skip.setValue(
            self._s.get("skip_frames", config.SKIP_FRAMES)
        )
        self._spin_skip.setToolTip(
            "每 N 帧推理一次（1=每帧都推理）\n"
            "CPU 较慢时建议设 4~6，GPU 可设 1~2"
        )
        form.addRow("跳帧间隔 N：", self._spin_skip)

        # 推理设备提示（只读展示）
        lbl_device = QLabel(f"当前推理设备：{config.DEVICE.upper()}")
        lbl_device.setStyleSheet("color: #666; font-size: 11px;")
        form.addRow("", lbl_device)

        layout.addWidget(box)
        layout.addStretch()
        return tab

    # ──────────────────────────────────────────────────────────
    #  Tab 3：存储设置
    # ──────────────────────────────────────────────────────────
    def _build_storage_tab(self) -> QWidget:
        tab    = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)

        box  = QGroupBox("截图与记录保留策略")
        form = QFormLayout(box)
        form.setSpacing(10)

        # 保留天数
        self._spin_retain = QSpinBox()
        self._spin_retain.setRange(1, 365)
        self._spin_retain.setValue(self._s["retain_days"])
        self._spin_retain.setSuffix(" 天")
        self._spin_retain.setToolTip(
            "截图文件和数据库记录的最长保留天数\n"
            "超期文件由 CaptureManager 自动清理"
        )
        form.addRow("保留天数：", self._spin_retain)

        # 截图目录（只读展示）
        lbl_cap_dir = QLabel(os.path.abspath(config.CAPTURE_DIR))
        lbl_cap_dir.setStyleSheet(
            "color: #1a5fa8; font-size: 11px; font-family: Consolas, monospace;"
        )
        lbl_cap_dir.setWordWrap(True)
        form.addRow("截图目录：", lbl_cap_dir)

        # 数据库路径（只读展示）
        lbl_db = QLabel(os.path.abspath(config.DB_PATH))
        lbl_db.setStyleSheet(
            "color: #1a5fa8; font-size: 11px; font-family: Consolas, monospace;"
        )
        lbl_db.setWordWrap(True)
        form.addRow("数据库路径：", lbl_db)

        layout.addWidget(box)
        layout.addStretch()
        return tab

    # ──────────────────────────────────────────────────────────
    #  流地址预览（实时联动）
    # ──────────────────────────────────────────────────────────
    def _build_url_preview(self) -> str:
        host = self._s["esp32_host"]
        port = self._s["stream_port"]
        return f"http://{host}:{port}/stream"

    def _refresh_url_preview(self):
        host = self._edit_host.text().strip()
        port = self._spin_stream_port.value()
        self._lbl_preview.setText(f"http://{host}:{port}/stream")

    # ──────────────────────────────────────────────────────────
    #  浏览模型权重文件
    # ──────────────────────────────────────────────────────────
    def _browse_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择模型权重文件",
            os.path.dirname(self._edit_model.text()) or ".",
            "PyTorch 权重 (*.pt);;所有文件 (*)"
        )
        if path:
            self._edit_model.setText(path)

    # ──────────────────────────────────────────────────────────
    #  参数校验
    # ──────────────────────────────────────────────────────────
    def _validate(self) -> tuple[bool, str]:
        """
        校验所有输入参数。
        返回 (True, "") 表示全部合法；
        返回 (False, "错误描述") 表示有问题。
        """
        ip = self._edit_host.text().strip()
        if not self._validate_ip(ip):
            return False, f"IP 地址格式错误：「{ip}」\n格式示例：192.168.1.101"

        model_path = self._edit_model.text().strip()
        if not model_path:
            return False, "模型路径不能为空"
        if not os.path.exists(model_path):
            return False, f"模型文件不存在：\n{model_path}\n请确认 best.pt 已放入 models/ 目录"

        return True, ""

    @staticmethod
    def _validate_ip(ip: str) -> bool:
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        try:
            return all(0 <= int(p) <= 255 for p in parts)
        except ValueError:
            return False

    # ──────────────────────────────────────────────────────────
    #  确定按钮：校验 → 保存 → 关闭
    # ──────────────────────────────────────────────────────────
    def _on_accept(self):
        ok, err = self._validate()
        if not ok:
            QMessageBox.warning(self, "参数错误", err)
            return

        # 构建新配置
        new_s = load_settings()
        new_s["esp32_host"]  = self._edit_host.text().strip()
        new_s["stream_port"] = self._spin_stream_port.value()
        new_s["tcp_port"]    = self._spin_tcp_port.value()
        new_s["model_path"]  = self._edit_model.text().strip()
        new_s["conf_thres"]  = round(self._spin_conf.value(), 2)
        new_s["retain_days"] = self._spin_retain.value()
        new_s["skip_frames"] = self._spin_skip.value()

        save_settings(new_s)
        self._s = new_s
        log.info(f"设置已保存：{new_s}")
        self.accept()

    # ──────────────────────────────────────────────────────────
    #  恢复默认值（从 config.py 默认值重置各控件）
    # ──────────────────────────────────────────────────────────
    def _restore_defaults(self):
        reply = QMessageBox.question(
            self, "恢复默认",
            "确定将所有参数恢复为默认值吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        self._edit_host.setText(config.ESP32_HOST)
        self._spin_stream_port.setValue(config.STREAM_PORT)
        self._spin_tcp_port.setValue(config.TCP_PORT)
        self._edit_model.setText(config.MODEL_PATH)
        self._spin_conf.setValue(config.CONF_THRES)
        self._spin_skip.setValue(config.SKIP_FRAMES)
        self._spin_retain.setValue(config.RETAIN_DAYS)
        self._refresh_url_preview()
        log.info("设置已恢复默认值（未保存，需点击「保存」生效）")

    # ──────────────────────────────────────────────────────────
    #  对外接口（供 MainWindow._open_settings() 调用）
    # ──────────────────────────────────────────────────────────
    def get_host(self) -> str:
        """返回保存后的 ESP32-CAM IP 地址"""
        return self._s["esp32_host"]

    def get_stream_url(self) -> str:
        """返回保存后的完整 MJPEG 流地址"""
        host = self._s["esp32_host"]
        port = self._s["stream_port"]
        return f"http://{host}:{port}/stream"

    def get_tcp_port(self) -> int:
        """返回保存后的 TCP 控制端口"""
        return self._s["tcp_port"]