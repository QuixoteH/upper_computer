# =============================================================
#  core/device_manager.py  —  ESP32-CAM 设备管理器
#  职责：
#    1. 通过 TCP:8888 发送唤醒/休眠指令给 ESP32-CAM
#    2. 轮询 HTTP 流端口检测设备是否在线
#    3. 向主线程发送设备上线/下线信号
#  对应系统设计：上位机→TCP:8888→ESP32-CAM，手动/自动启动两种模式
# =============================================================

import socket
import threading
import logging
import time
import urllib.request
import urllib.error
from PyQt5.QtCore import QObject, pyqtSignal

import config

log = logging.getLogger(__name__)

# TCP 指令定义（与 ESP32-CAM 固件约定一致）
_CMD_WAKE  = b"WAKE\r\n"
_CMD_SLEEP = b"SLEEP\r\n"

# 轮询间隔（秒）
_POLL_INTERVAL_SEC = 3

# TCP / HTTP 超时（秒）
_TCP_TIMEOUT  = 3
_HTTP_TIMEOUT = 2


class DeviceManager(QObject):

    # ── 信号定义 ──────────────────────────────────────────────
    device_online  = pyqtSignal()        # 设备从离线变为在线时发出
    device_offline = pyqtSignal()        # 设备从在线变为离线时发出
    cmd_result     = pyqtSignal(bool, str)
    # bool : True=指令发送成功  False=失败
    # str  : 结果描述，供 AlertPanel 显示

    def __init__(self,
                 host:     str = config.TCP_HOST,
                 tcp_port: int = config.TCP_PORT,
                 stream_url: str = config.STREAM_URL):
        super().__init__()
        self.host       = host
        self.tcp_port   = tcp_port
        self.stream_url = stream_url

        self._polling        = False
        self._poll_thread: threading.Thread | None = None
        self._last_online    = False   # 上次轮询时的在线状态，用于边沿检测

    # ──────────────────────────────────────────────────────────
    #  TCP 指令：唤醒（手动启动监测时调用）
    # ──────────────────────────────────────────────────────────
    def send_wake(self) -> bool:
        """
        向 ESP32-CAM 发送 WAKE 指令，触发其开启 MJPEG 推流。
        对应系统设计中"上位机手动启动"模式。
        返回 True=发送成功，False=连接失败（设备可能未上电）
        """
        return self._send_tcp_cmd(_CMD_WAKE, "唤醒")

    # ──────────────────────────────────────────────────────────
    #  TCP 指令：休眠（停止监测时调用，可选）
    # ──────────────────────────────────────────────────────────
    def send_sleep(self) -> bool:
        """
        向 ESP32-CAM 发送 SLEEP 指令，触发其关闭推流进入低功耗。
        注意：若 ESP32-CAM 固件未实现此指令，发送后无副作用。
        """
        return self._send_tcp_cmd(_CMD_SLEEP, "休眠")

    # ──────────────────────────────────────────────────────────
    #  内部：发送 TCP 指令
    # ──────────────────────────────────────────────────────────
    def _send_tcp_cmd(self, cmd: bytes, label: str) -> bool:
        """
        通用 TCP 指令发送，带超时和完整错误处理。
        所有异常均被捕获，不会向上抛出，保证 UI 不崩溃。
        """
        log.info(f"发送 {label} 指令 → {self.host}:{self.tcp_port}")
        try:
            with socket.create_connection(
                (self.host, self.tcp_port),
                timeout=_TCP_TIMEOUT
            ) as s:
                s.sendall(cmd)
                # 短暂等待可能的 ACK 响应（固件有响应则读取，无则忽略）
                s.settimeout(0.5)
                try:
                    ack = s.recv(64)
                    log.debug(f"ESP32-CAM ACK：{ack.decode(errors='ignore').strip()}")
                except (socket.timeout, ConnectionResetError):
                    pass   # 无响应属正常，继续

            msg = f"{label} 指令已发送至 {self.host}:{self.tcp_port}"
            log.info(msg)
            self.cmd_result.emit(True, msg)
            return True

        except ConnectionRefusedError:
            msg = f"{label} 失败：{self.host}:{self.tcp_port} 拒绝连接（设备未上电或端口未开放）"
        except socket.timeout:
            msg = f"{label} 失败：连接 {self.host}:{self.tcp_port} 超时"
        except OSError as e:
            msg = f"{label} 失败：{e}"

        log.warning(msg)
        self.cmd_result.emit(False, msg)
        return False

    # ──────────────────────────────────────────────────────────
    #  在线检测：检查 HTTP 流端口是否可访问
    # ──────────────────────────────────────────────────────────
    def check_stream_alive(self) -> bool:
        """
        向 ESP32-CAM 的 MJPEG 流地址发送 HEAD/GET 请求，
        判断设备是否在线且推流正常。
        返回 True=在线，False=离线或不可达
        注意：此方法为阻塞调用，不应在主线程直接调用。
        """
        try:
            req = urllib.request.Request(
                self.stream_url,
                method="GET",
                headers={"User-Agent": "PestMonitor/1.0"}
            )
            # 仅需收到 HTTP 响应头即可判断在线，立即关闭连接
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                online = (resp.status == 200)
                log.debug(f"流检测：{self.stream_url}  HTTP {resp.status}")
                return online
        except (urllib.error.URLError, OSError, Exception):
            return False

    # ──────────────────────────────────────────────────────────
    #  轮询：后台线程定期检测设备在线状态
    # ──────────────────────────────────────────────────────────
    def start_polling(self):
        """
        启动后台轮询线程，每 _POLL_INTERVAL_SEC 秒检测一次设备在线状态。
        检测到状态变化时发出 device_online / device_offline 信号。
        """
        if self._polling:
            log.warning("轮询线程已在运行，忽略重复启动")
            return

        self._polling     = True
        self._last_online = False
        self._poll_thread = threading.Thread(
            target    = self._poll_loop,
            daemon    = True,
            name      = "DevicePollThread"
        )
        self._poll_thread.start()
        log.info(f"设备轮询已启动（间隔 {_POLL_INTERVAL_SEC}s）")

    def stop_polling(self):
        """停止后台轮询线程"""
        self._polling = False
        # daemon 线程无需 join，标志位置 False 后下次循环自然退出
        log.info("设备轮询已停止")

    def _poll_loop(self):
        """
        轮询主循环：
        - 设备从离线→在线：发 device_online 信号
        - 设备从在线→离线：发 device_offline 信号
        - 状态未变化：静默
        """
        while self._polling:
            current_online = self.check_stream_alive()

            if current_online and not self._last_online:
                log.info(f"设备上线：{self.host}")
                self.device_online.emit()
            elif not current_online and self._last_online:
                log.warning(f"设备下线：{self.host}")
                self.device_offline.emit()

            self._last_online = current_online

            # 分段睡眠，使 stop_polling() 能快速响应
            for _ in range(_POLL_INTERVAL_SEC * 10):
                if not self._polling:
                    break
                time.sleep(0.1)

        log.debug("_poll_loop 已退出")

    # ──────────────────────────────────────────────────────────
    #  运行时更新设备地址（SettingsDialog 保存后调用）
    # ──────────────────────────────────────────────────────────
    def update_host(self, host: str,
                    tcp_port:   int = None,
                    stream_url: str = None):
        """
        更新设备地址。若轮询正在运行，需先 stop_polling() 再 start_polling()。
        """
        old = self.host
        self.host       = host
        self.tcp_port   = tcp_port   or self.tcp_port
        self.stream_url = stream_url or self.stream_url
        log.info(f"设备地址更新：{old} → {self.host}")

    # ──────────────────────────────────────────────────────────
    #  属性：当前在线状态（最近一次轮询结果）
    # ──────────────────────────────────────────────────────────
    @property
    def is_online(self) -> bool:
        return self._last_online