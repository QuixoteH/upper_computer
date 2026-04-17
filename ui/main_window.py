# =============================================================
#  ui/main_window.py  —  主窗口（程序骨架与模块组装中心）
#  v3.0 新增：
#    - 工具栏 IP 输入框：随时修改 ESP32-CAM 地址并持久化
#    - 摄像头设置按钮：一键在浏览器打开 ESP32-CAM Web 管理页
#    - 启动时从 settings.json 读取 IP 等配置
# =============================================================

import queue
import logging
import webbrowser                      # v3.0 新增，Python 内置库

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QTabWidget, QMenuBar, QAction, QMessageBox,
    QStatusBar, QLabel, QSizePolicy,
    QToolBar, QLineEdit, QPushButton    # v3.0 新增
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QCloseEvent

from core.stream_thread   import StreamThread
from core.detect_thread   import DetectThread
from core.device_manager  import DeviceManager
from core.capture_manager import CaptureManager
from db.database          import Database
from ui.video_widget      import VideoWidget
from ui.alert_panel       import AlertPanel
from ui.history_widget    import HistoryWidget
from ui.settings_dialog   import SettingsDialog

import config
from config import load_settings, save_settings   # v3.0 新增

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.WIN_TITLE)
        self.resize(config.WIN_WIDTH, config.WIN_HEIGHT)

        # ── Step 1：加载运行时配置（v3.0 新增）──────────────────
        # 首次运行时 settings.json 不存在，load_settings() 自动从
        # config.py 默认值生成，后续用户改动均持久化到 settings.json
        self._settings = load_settings()
        _host      = self._settings["esp32_host"]
        _sport     = self._settings["stream_port"]
        _tcp_port  = self._settings["tcp_port"]
        _stream_url = f"http://{_host}:{_sport}/stream"

        # ── Step 2：数据层初始化 ──────────────────────────────
        self.db = Database(config.DB_PATH)
        self.db.cleanup_old_records()

        # ── Step 3：唯一创建 frame_queue ──────────────────────
        # ⚠ 必须在此处唯一创建并注入，两个线程不得各自 new Queue()
        self.frame_queue = queue.Queue(maxsize=config.QUEUE_SIZE)

        # ── Step 4：核心模块实例化（地址来自 settings，v3.0 修改）
        self.stream = StreamThread(
            frame_queue=self.frame_queue,
            url=_stream_url
        )
        self.detector = DetectThread(
            frame_queue=self.frame_queue,
            db=self.db,
            model_path=self._settings["model_path"]
        )
        self.device = DeviceManager(
            host=_host,
            tcp_port=_tcp_port,
            stream_url=_stream_url
        )

        # ── Step 5：构建 UI ───────────────────────────────────
        self._build_ui()
        self._build_toolbar()     # v3.0 新增：IP 工具栏
        self._build_menu()
        self._build_statusbar()

        # ── Step 6：连接所有信号槽 ────────────────────────────
        self._connect_signals()

        # ── Step 7：启动设备轮询 ──────────────────────────────
        self.device.start_polling()

        # ── Step 8：定时刷新今日统计（每 10 秒）──────────────
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(10_000)
        self._stats_timer.timeout.connect(self._refresh_today_stats)
        self._stats_timer.start()

        self._monitoring = False
        log.info("MainWindow 初始化完成")

    # ──────────────────────────────────────────────────────────
    #  UI 构建
    # ──────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 上半：视频区（左）+ 控制面板（右）
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.video_widget = VideoWidget()
        self.video_widget.setMinimumSize(config.VIDEO_W, config.VIDEO_H)
        self.video_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )

        self.alert_panel = AlertPanel()
        self.alert_panel.setFixedWidth(280)

        top_layout.addWidget(self.video_widget, stretch=1)
        top_layout.addWidget(self.alert_panel,  stretch=0)

        # 下半：历史 Tab
        self.tab = QTabWidget()
        self.history_widget = HistoryWidget(self.db)
        self.tab.addTab(self.history_widget, "📋  历史检测记录")
        self.tab.setFixedHeight(240)

        root.addWidget(top_widget, stretch=1)
        root.addWidget(self.tab,   stretch=0)

    # ──────────────────────────────────────────────────────────
    #  v3.0 新增：IP 工具栏
    # ──────────────────────────────────────────────────────────
    def _build_toolbar(self):
        """
        构建顶部工具栏，包含：
          - ESP32-CAM IP 输入框（支持 Enter 键保存）
          - 保存并重连按钮
          - 摄像头设置按钮（打开浏览器）
        """
        toolbar = QToolBar("ESP32-CAM 连接")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addWidget(QLabel("  ESP32-CAM IP："))

        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("192.168.x.x")
        self.ip_input.setText(self._settings["esp32_host"])
        self.ip_input.setFixedWidth(150)
        self.ip_input.setToolTip(
            "输入 ESP32-CAM 的 IP 地址，点击「保存并重连」或按 Enter 生效"
        )
        self.ip_input.returnPressed.connect(self._apply_ip)
        toolbar.addWidget(self.ip_input)

        toolbar.addWidget(QLabel("  "))

        btn_apply = QPushButton("✓ 保存并重连")
        btn_apply.setToolTip("保存 IP 到 settings.json 并重新连接设备")
        btn_apply.clicked.connect(self._apply_ip)
        toolbar.addWidget(btn_apply)

        toolbar.addSeparator()

        btn_cam = QPushButton("🎥 摄像头设置")
        btn_cam.setToolTip("在默认浏览器中打开 ESP32-CAM Web 管理界面")
        btn_cam.clicked.connect(self._open_cam_settings)
        toolbar.addWidget(btn_cam)

    def _build_menu(self):
        menubar: QMenuBar = self.menuBar()

        # 监测菜单
        menu_monitor = menubar.addMenu("监测")

        self.action_start = QAction("▶  启动监测", self)
        self.action_start.setShortcut("Ctrl+R")
        self.action_start.triggered.connect(self.start_monitoring)

        self.action_stop = QAction("■  停止监测", self)
        self.action_stop.setShortcut("Ctrl+S")
        self.action_stop.setEnabled(False)
        self.action_stop.triggered.connect(self.stop_monitoring)

        self.action_wake = QAction("⚡  发送唤醒指令", self)
        self.action_wake.triggered.connect(lambda: self.device.send_wake())

        menu_monitor.addAction(self.action_start)
        menu_monitor.addAction(self.action_stop)
        menu_monitor.addSeparator()
        menu_monitor.addAction(self.action_wake)

        # 设置菜单
        menu_settings = menubar.addMenu("设置")

        action_settings = QAction("⚙  连接与模型设置…", self)
        action_settings.triggered.connect(self._open_settings)
        menu_settings.addAction(action_settings)

        action_export = QAction("📤  导出检测记录 CSV…", self)
        action_export.triggered.connect(self.history_widget.export_csv)
        menu_settings.addAction(action_export)

        # 帮助菜单
        menu_help = menubar.addMenu("帮助")
        action_about = QAction("关于", self)
        action_about.triggered.connect(self._show_about)
        menu_help.addAction(action_about)

    def _build_statusbar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.lbl_conn  = QLabel("● 未连接")
        self.lbl_conn.setStyleSheet("color: #888;")

        self.lbl_infer = QLabel("推理：-- ms")
        self.lbl_today = QLabel("今日检测：0 次")

        self.status_bar.addWidget(self.lbl_conn)
        self.status_bar.addWidget(QLabel("  |  "))
        self.status_bar.addWidget(self.lbl_infer)
        self.status_bar.addPermanentWidget(self.lbl_today)

    # ──────────────────────────────────────────────────────────
    #  信号槽连接（所有跨模块通信在此统一声明）
    # ──────────────────────────────────────────────────────────
    def _connect_signals(self):
        # StreamThread → UI
        self.stream.conn_status.connect(self._on_conn_status)

        # DetectThread → UI
        self.detector.result_ready.connect(self.video_widget.update_frame)
        self.detector.result_ready.connect(self.alert_panel.update_detection)
        self.detector.result_ready.connect(self._on_result_ready)
        self.detector.model_ready.connect(self._on_model_ready)
        self.detector.detect_error.connect(self._on_detect_error)

        # DeviceManager → UI
        self.device.device_online.connect(self._on_device_online)
        self.device.device_offline.connect(self._on_device_offline)
        self.device.cmd_result.connect(self._on_cmd_result)

        # AlertPanel 按钮 → MainWindow
        self.alert_panel.btn_start.clicked.connect(self.start_monitoring)
        self.alert_panel.btn_stop.clicked.connect(self.stop_monitoring)
        self.alert_panel.btn_wake.clicked.connect(lambda: self.device.send_wake())

    # ──────────────────────────────────────────────────────────
    #  v3.0 新增：IP 保存与摄像头设置
    # ──────────────────────────────────────────────────────────
    def _apply_ip(self):
        """
        读取工具栏 IP 输入框的值，校验格式后：
          1. 写入 settings.json 持久化
          2. 动态更新 StreamThread 和 DeviceManager 的连接地址
          3. 若正在监测，自动 stop → 更新地址 → 重新 start
        """
        ip = self.ip_input.text().strip()
        if not self._validate_ip(ip):
            QMessageBox.warning(
                self, "IP 格式错误",
                f"「{ip}」不是有效的 IPv4 地址\n"
                "格式示例：192.168.1.101（每段 0~255）"
            )
            return

        # 更新 settings.json
        s = load_settings()
        s["esp32_host"] = ip
        save_settings(s)
        self._settings = s

        sport    = s["stream_port"]
        tcp_port = s["tcp_port"]
        new_url  = f"http://{ip}:{sport}/stream"

        was_monitoring = self._monitoring
        if was_monitoring:
            self.stop_monitoring()

        self.stream.update_url(new_url)
        self.device.update_host(ip, tcp_port, new_url)

        log.info(f"IP 已更新：{ip}  流地址：{new_url}")
        self.status_bar.showMessage(f"IP 已更新为 {ip}，连接中…", 4000)

        if was_monitoring:
            self.start_monitoring()

    def _open_cam_settings(self):
        """在默认浏览器打开 ESP32-CAM Web 管理页面（内置 HTTP 服务器）"""
        ip  = self.ip_input.text().strip()
        url = f"http://{ip}"
        webbrowser.open(url)
        self.status_bar.showMessage(f"已在浏览器打开：{url}", 3000)
        log.info(f"打开摄像头设置页面：{url}")

    @staticmethod
    def _validate_ip(ip: str) -> bool:
        """校验 IPv4 格式：必须是四段，每段均为 0~255 的整数"""
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        try:
            return all(0 <= int(p) <= 255 for p in parts)
        except ValueError:
            return False

    # ──────────────────────────────────────────────────────────
    #  监测会话：启动
    # ──────────────────────────────────────────────────────────
    def start_monitoring(self):
        if self._monitoring:
            log.debug("监测已在运行，忽略重复启动")
            return

        log.info("启动监测会话")
        self.device.send_wake()

        # 清空帧队列中的残留旧帧
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break

        self.stream.start()
        self.detector.start()
        self._monitoring = True
        self._update_btn_state(monitoring=True)
        self.status_bar.showMessage("监测已启动", 3000)
        log.info("StreamThread 与 DetectThread 已启动")

    # ──────────────────────────────────────────────────────────
    #  监测会话：停止
    # ──────────────────────────────────────────────────────────
    def stop_monitoring(self):
        if not self._monitoring:
            return

        log.info("停止监测会话")
        self.stream.stop()
        self.detector.stop()
        self._monitoring = False
        self._update_btn_state(monitoring=False)
        self.video_widget.show_idle()
        self.status_bar.showMessage("监测已停止", 3000)

    # ──────────────────────────────────────────────────────────
    #  槽函数
    # ──────────────────────────────────────────────────────────
    def _on_conn_status(self, online: bool, msg: str):
        if online:
            self.lbl_conn.setText("● 已连接")
            self.lbl_conn.setStyleSheet("color: #2e7d32; font-weight: bold;")
        else:
            self.lbl_conn.setText("● 未连接")
            self.lbl_conn.setStyleSheet("color: #c62828;")
        self.alert_panel.update_conn_status(online, msg)

    def _on_result_ready(self, frame, detections: list):
        avg_ms = self.detector.avg_infer_ms
        if avg_ms > 0:
            self.lbl_infer.setText(f"推理：{avg_ms:.0f} ms")

    def _on_model_ready(self, model_path: str):
        self.status_bar.showMessage(f"模型已加载：{model_path}", 5000)
        log.info(f"模型加载完成：{model_path}")

    def _on_detect_error(self, msg: str):
        log.error(f"检测异常：{msg}")
        QMessageBox.critical(self, "检测错误", msg)
        if self._monitoring:
            self.stop_monitoring()

    def _on_device_online(self):
        log.info("检测到 ESP32-CAM 上线")
        self.status_bar.showMessage("ESP32-CAM 已上线", 3000)
        # 对应 STM32 → GPIO33 触发的自动启动链路
        if not self._monitoring:
            self.start_monitoring()

    def _on_device_offline(self):
        log.warning("ESP32-CAM 下线")
        self.status_bar.showMessage("ESP32-CAM 已下线", 3000)

    def _on_cmd_result(self, success: bool, msg: str):
        self.status_bar.showMessage(msg, 4000)

    def _refresh_today_stats(self):
        try:
            rows  = self.db.query_today_statistics()
            total = sum(r["total_count"] for r in rows)
            self.lbl_today.setText(f"今日检测：{total} 次")
            self.alert_panel.update_statistics(rows)
        except Exception as e:
            log.warning(f"刷新统计失败：{e}")

    # ──────────────────────────────────────────────────────────
    #  设置对话框（高级参数）
    # ──────────────────────────────────────────────────────────
    def _open_settings(self):
        """
        打开详细设置对话框（模型路径/置信度等高级参数）。
        保存后同步更新工具栏 IP 输入框。
        """
        dlg = SettingsDialog(self)
        if dlg.exec_():
            new_url  = dlg.get_stream_url()
            new_host = dlg.get_host()
            new_port = dlg.get_tcp_port()

            was_monitoring = self._monitoring
            if was_monitoring:
                self.stop_monitoring()

            self.stream.update_url(new_url)
            self.device.update_host(new_host, new_port, new_url)

            # v3.0：同步更新工具栏 IP 输入框显示
            self.ip_input.setText(new_host)

            # 持久化保存
            s = load_settings()
            s["esp32_host"] = new_host
            s["tcp_port"]   = new_port
            save_settings(s)
            self._settings = s

            log.info(f"设置已更新：host={new_host}  stream={new_url}")

            if was_monitoring:
                self.start_monitoring()

    def _show_about(self):
        QMessageBox.about(
            self, "关于",
            f"<b>{config.WIN_TITLE}</b><br>"
            "农作物害虫识别上位机<br><br>"
            "物理2201 · 黄海 · A13220499<br>"
            "Python 3.10 + PyQt5 + Ultralytics"
        )

    def _update_btn_state(self, monitoring: bool):
        """同步菜单栏和 AlertPanel 按钮的启用状态"""
        self.action_start.setEnabled(not monitoring)
        self.action_stop.setEnabled(monitoring)
        self.alert_panel.set_monitoring_state(monitoring)

    # ──────────────────────────────────────────────────────────
    #  程序退出：按顺序安全释放资源
    # ──────────────────────────────────────────────────────────
    def closeEvent(self, event: QCloseEvent):
        reply = QMessageBox.question(
            self, "退出确认",
            "确定要退出害虫识别系统吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.No:
            event.ignore()
            return

        log.info("程序退出，清理资源…")
        # 顺序：定时器 → 轮询 → 推理线程 → 数据库
        self._stats_timer.stop()
        self.device.stop_polling()
        if self._monitoring:
            self.stop_monitoring()
        self.db.close()
        log.info("资源释放完毕，程序退出")
        event.accept()
