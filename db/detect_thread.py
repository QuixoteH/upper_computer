# =============================================================
#  core/detect_thread.py  —  YOLOv8 推理线程
#  职责：从 frame_queue 取帧 → YOLO 推理 → 截图/写库 → 发送结果信号
#  线程安全：frame_queue 和 db 均由 MainWindow 注入，非本模块创建
# =============================================================

import queue
import logging
import time
from datetime import datetime
from typing import Optional

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from ultralytics import YOLO

from core.capture_manager import CaptureManager
from db.database import Database
import config

log = logging.getLogger(__name__)


class DetectThread(QThread):

    # ── 信号定义 ──────────────────────────────────────────────
    result_ready  = pyqtSignal(object, list)
    # object : 标注帧 numpy BGR（由 VideoWidget 做 BGR→RGB 转换后显示）
    # list   : 检测结果列表，每项为 dict，见 _parse_detections()

    model_ready   = pyqtSignal(str)
    # str    : 模型路径，模型加载完成后发出，供 UI 解除"加载中"状态

    detect_error  = pyqtSignal(str)
    # str    : 错误描述，模型加载失败或推理异常时发出

    # ── 截图最小间隔（同一虫种两次截图至少间隔此秒数，防止磁盘爆满）──
    _CAPTURE_INTERVAL_SEC = 10

    # ──────────────────────────────────────────────────────────
    #  初始化（在主线程中执行，不在此处加载模型）
    # ──────────────────────────────────────────────────────────
    def __init__(self,
                 frame_queue: queue.Queue,
                 db: Database,
                 model_path: str = config.MODEL_PATH):
        super().__init__()
        self.frame_queue  = frame_queue   # 由 MainWindow 注入
        self.db           = db            # 由 MainWindow 注入
        self.model_path   = model_path
        self.capture_mgr  = CaptureManager(config.CAPTURE_DIR,
                                           config.RETAIN_DAYS)
        self._running     = False

        # 跳帧计数器
        self._frame_idx   = 0

        # 截图冷却：记录各虫种上次截图时间 {class_name: timestamp}
        self._last_capture_time: dict[str, float] = {}

        # 推理统计（调试用）
        self._infer_count = 0
        self._infer_total_ms = 0.0

    # ──────────────────────────────────────────────────────────
    #  QThread 主循环
    # ──────────────────────────────────────────────────────────
    def run(self):
        self._running = True
        log.info(f"DetectThread 启动，加载模型：{self.model_path}")

        # ── 模型加载（在子线程中执行，不阻塞 UI）──
        model = self._load_model()
        if model is None:
            return   # 加载失败，detect_error 信号已在 _load_model() 发出

        log.info("模型加载完成，开始推理循环")
        self.model_ready.emit(self.model_path)

        while self._running:
            # ── 取帧（带超时，保证 stop() 后能快速退出）──
            frame = self._get_frame()
            if frame is None:
                continue   # queue.Empty 超时，检查 _running 后继续

            # ── 跳帧（每 SKIP_FRAMES 帧推理一次）──
            self._frame_idx += 1
            if self._frame_idx % config.SKIP_FRAMES != 0:
                continue

            # ── YOLO 推理 ──
            annotated, detections = self._infer(model, frame)
            if annotated is None:
                continue   # 推理异常，已记录日志，跳过本帧

            # ── 截图 + 写库（仅在有检测结果时）──
            if detections:
                self._handle_detections(detections, annotated)

            # ── 发信号给主线程（无论是否有检测结果，都刷新视频画面）──
            self.result_ready.emit(annotated, detections)

        log.info("DetectThread 已退出 run()")

    # ──────────────────────────────────────────────────────────
    #  模型加载
    # ──────────────────────────────────────────────────────────
    def _load_model(self) -> Optional[YOLO]:
        try:
            model = YOLO(self.model_path)
            # 预热推理：用全零帧跑一次，避免第一帧延迟过高
            dummy = np.zeros((480, 640, 3), dtype=np.uint8)
            model.predict(dummy, verbose=False, device=config.DEVICE)
            log.info(f"模型预热完成，推理设备：{config.DEVICE}")
            return model
        except FileNotFoundError:
            msg = f"模型文件不存在：{self.model_path}，请将 best.pt 放入 models/ 目录"
            log.error(msg)
            self.detect_error.emit(msg)
            return None
        except Exception as e:
            msg = f"模型加载失败：{e}"
            log.error(msg)
            self.detect_error.emit(msg)
            return None

    # ──────────────────────────────────────────────────────────
    #  取帧（带超时，可中断）
    # ──────────────────────────────────────────────────────────
    def _get_frame(self) -> Optional[np.ndarray]:
        """从 frame_queue 取一帧，1 秒超时。Empty 时返回 None。"""
        try:
            return self.frame_queue.get(timeout=1)
        except queue.Empty:
            return None

    # ──────────────────────────────────────────────────────────
    #  YOLO 推理（关键：必须取 [0]）
    # ──────────────────────────────────────────────────────────
    def _infer(self, model: YOLO, frame: np.ndarray):
        """
        返回 (annotated_frame, detections_list)。
        推理异常时返回 (None, None)。

        ⚠ model.predict() 返回列表，必须取 [0] 才能调用 .plot() 和 .boxes
        """
        try:
            t0 = time.time()

            results = model.predict(
                frame,
                conf    = config.CONF_THRES,
                iou     = config.IOU_THRES,
                device  = config.DEVICE,
                verbose = False,
            )[0]   # ← 必须取 [0]，results 本身是列表

            elapsed_ms = (time.time() - t0) * 1000
            self._infer_count    += 1
            self._infer_total_ms += elapsed_ms
            log.debug(f"推理耗时 {elapsed_ms:.1f}ms  "
                      f"均值 {self._infer_total_ms/self._infer_count:.1f}ms")

            annotated  = results.plot()           # 绘制检测框，返回 BGR numpy
            detections = self._parse_detections(results, model.names)
            return annotated, detections

        except Exception as e:
            log.error(f"推理异常：{e}")
            self.detect_error.emit(f"推理异常：{e}")
            return None, None

    # ──────────────────────────────────────────────────────────
    #  解析检测结果
    # ──────────────────────────────────────────────────────────
    @staticmethod
    def _parse_detections(results, names: dict) -> list[dict]:
        """
        将 results.boxes 转为统一格式的字典列表：
        [
          {
            "class_id":   int,
            "class_name": str,
            "confidence": float,   # 保留 3 位小数
            "bbox":       [x1, y1, x2, y2]  # 像素坐标，float
          },
          ...
        ]
        """
        detections = []
        for box in results.boxes:
            class_id = int(box.cls[0])
            detections.append({
                "class_id":   class_id,
                "class_name": names[class_id],
                "confidence": round(float(box.conf[0]), 3),
                "bbox":       box.xyxy[0].tolist(),
            })
        return detections

    # ──────────────────────────────────────────────────────────
    #  截图 + 写库逻辑
    # ──────────────────────────────────────────────────────────
    def _handle_detections(self, detections: list[dict],
                           annotated: np.ndarray):
        """
        对检测结果执行：
        1. 计算每种虫的汇总统计（数量 + 平均置信度）
        2. 按截图冷却时间决定是否截图
        3. 写入 detections 表
        4. 如有新害虫出现，写入 alert_logs 表
        """
        # ── 按虫种聚合（一帧可能检测到多个同类虫）──
        aggregated: dict[str, dict] = {}
        for d in detections:
            name = d["class_name"]
            if name not in aggregated:
                aggregated[name] = {"count": 0, "conf_sum": 0.0}
            aggregated[name]["count"]    += 1
            aggregated[name]["conf_sum"] += d["confidence"]

        now = time.time()

        for class_name, stats in aggregated.items():
            count   = stats["count"]
            avg_conf = round(stats["conf_sum"] / count, 3)

            # ── 截图冷却判断 ──
            last_t = self._last_capture_time.get(class_name, 0.0)
            cap_path = None
            if now - last_t >= self._CAPTURE_INTERVAL_SEC:
                try:
                    cap_path = self.capture_mgr.save(annotated)
                    self._last_capture_time[class_name] = now
                    log.info(f"截图已保存：{cap_path}  [{class_name} ×{count}]")
                except Exception as e:
                    log.error(f"截图保存失败：{e}")

            # ── 写入检测记录 ──
            try:
                self.db.save_detection(
                    pest_class   = class_name,
                    count        = count,
                    confidence   = avg_conf,
                    capture_path = cap_path,
                )
            except Exception as e:
                log.error(f"写入检测记录失败：{e}")

            # ── 写入告警（首次检测到此虫种时触发告警）──
            if last_t == 0.0:
                try:
                    self.db.save_alert(
                        alert_type = "pest",
                        message    = f"检测到害虫：{class_name}，数量 {count}，"
                                     f"置信度 {avg_conf:.1%}"
                    )
                    log.info(f"害虫告警已写入：{class_name}")
                except Exception as e:
                    log.error(f"写入告警失败：{e}")

    # ──────────────────────────────────────────────────────────
    #  停止线程
    # ──────────────────────────────────────────────────────────
    def stop(self):
        log.info("DetectThread stop() 被调用")
        self._running = False
        self.quit()
        if not self.wait(5000):   # 模型推理最长可能 ~500ms，等 5s 足够
            log.warning("DetectThread 未在 5s 内退出，强制终止")
            self.terminate()
            self.wait()

    # ──────────────────────────────────────────────────────────
    #  属性：推理统计（供调试/UI 展示）
    # ──────────────────────────────────────────────────────────
    @property
    def avg_infer_ms(self) -> float:
        """返回平均推理耗时（毫秒）"""
        if self._infer_count == 0:
            return 0.0
        return round(self._infer_total_ms / self._infer_count, 1)

    @property
    def infer_count(self) -> int:
        return self._infer_count