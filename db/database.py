# =============================================================
#  db/database.py  —  SQLite 数据持久化层
#  职责：建表、写入检测记录、写入告警、历史查询、统计、清理
#  线程说明：DetectThread 写，MainWindow/HistoryWidget 读，
#            check_same_thread=False + 写锁保证安全
# =============================================================

import sqlite3
import os
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

import config

log = logging.getLogger(__name__)


class Database:

    def __init__(self, db_path: str = config.DB_PATH):
        # 自动创建 db/ 目录（若不存在）
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        # check_same_thread=False：允许 DetectThread 与主线程共用同一连接
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row   # 结果可按列名访问
        self._lock = threading.Lock()         # 写操作加锁，防止并发写冲突
        self._create_tables()
        self._create_indexes()
        log.info(f"数据库已连接：{db_path}")

    # ──────────────────────────────────────────────────────────
    #  建表
    # ──────────────────────────────────────────────────────────
    def _create_tables(self):
        with self._lock:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS detections (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp    TEXT    NOT NULL,          -- 'YYYY-MM-DD HH:MM:SS'
                    pest_class   TEXT    NOT NULL,          -- 害虫种类名
                    count        INTEGER NOT NULL DEFAULT 1,-- 同帧检测数量
                    confidence   REAL    NOT NULL,          -- 平均置信度
                    capture_path TEXT                       -- 截图相对路径，无截图为 NULL
                );

                CREATE TABLE IF NOT EXISTS alert_logs (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp    TEXT    NOT NULL,
                    alert_type   TEXT    NOT NULL,          -- 'pest' | 'disease' | 'system'
                    message      TEXT    NOT NULL,
                    is_read      INTEGER NOT NULL DEFAULT 0  -- 0=未读  1=已读
                );
            """)
            self.conn.commit()

    def _create_indexes(self):
        """在高频查询字段上建索引，加速历史查询和统计"""
        with self._lock:
            self.conn.executescript("""
                CREATE INDEX IF NOT EXISTS idx_detections_timestamp
                    ON detections(timestamp);
                CREATE INDEX IF NOT EXISTS idx_detections_pest_class
                    ON detections(pest_class);
                CREATE INDEX IF NOT EXISTS idx_alert_logs_is_read
                    ON alert_logs(is_read);
            """)
            self.conn.commit()

    # ──────────────────────────────────────────────────────────
    #  写入：检测记录
    # ──────────────────────────────────────────────────────────
    def save_detection(self,
                       pest_class: str,
                       count: int,
                       confidence: float,
                       capture_path: Optional[str] = None) -> int:
        """
        保存一条检测记录，返回新行 id。
        由 DetectThread 调用，加写锁。
        """
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO detections(timestamp, pest_class, count, confidence, capture_path) "
                "VALUES (?, ?, ?, ?, ?)",
                (ts, pest_class, count, round(confidence, 4), capture_path)
            )
            self.conn.commit()
        log.debug(f"检测记录已写入 id={cur.lastrowid}  {pest_class} ×{count}  conf={confidence:.3f}")
        return cur.lastrowid

    # ──────────────────────────────────────────────────────────
    #  写入：告警日志
    # ──────────────────────────────────────────────────────────
    def save_alert(self, alert_type: str, message: str) -> int:
        """
        保存告警记录（害虫告警 / 病害告警 / 系统异常）。
        alert_type: 'pest' | 'disease' | 'system'
        """
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO alert_logs(timestamp, alert_type, message) VALUES (?, ?, ?)",
                (ts, alert_type, message)
            )
            self.conn.commit()
        log.debug(f"告警已写入 type={alert_type}  msg={message}")
        return cur.lastrowid

    # ──────────────────────────────────────────────────────────
    #  查询：历史检测记录（HistoryWidget 使用）
    # ──────────────────────────────────────────────────────────
    def query_detections(self,
                         date_from: Optional[str] = None,
                         date_to: Optional[str] = None,
                         pest_class: Optional[str] = None,
                         days: int = 30) -> list:
        """
        查询检测历史，支持日期区间 + 虫种筛选。
        date_from / date_to 格式：'YYYY-MM-DD'
        未传 date_from/date_to 时，默认查最近 days 天。
        返回：list[sqlite3.Row]，可按列名索引。
        """
        if date_from is None:
            date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        if date_to is None:
            date_to = datetime.now().strftime("%Y-%m-%d")

        sql = ("SELECT id, timestamp, pest_class, count, confidence, capture_path "
               "FROM detections WHERE timestamp >= ? AND timestamp <= ?")
        params = [date_from + " 00:00:00", date_to + " 23:59:59"]

        if pest_class and pest_class not in ("", "全部害虫"):
            sql += " AND pest_class = ?"
            params.append(pest_class)

        sql += " ORDER BY timestamp DESC"
        return self.conn.execute(sql, params).fetchall()

    # ──────────────────────────────────────────────────────────
    #  查询：今日统计（AlertPanel 实时显示）
    # ──────────────────────────────────────────────────────────
    def query_today_statistics(self) -> list:
        """
        返回今日各虫种检测次数和总数量，供 AlertPanel 实时展示。
        返回：list[sqlite3.Row]  列：pest_class, times, total_count
        """
        today = datetime.now().strftime("%Y-%m-%d")
        sql = """
            SELECT pest_class,
                   COUNT(*)       AS times,
                   SUM(count)     AS total_count
            FROM   detections
            WHERE  timestamp >= ?
            GROUP  BY pest_class
            ORDER  BY total_count DESC
        """
        return self.conn.execute(sql, [today + " 00:00:00"]).fetchall()

    # ──────────────────────────────────────────────────────────
    #  查询：未读告警数量（AlertPanel 角标）
    # ──────────────────────────────────────────────────────────
    def get_unread_alert_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM alert_logs WHERE is_read = 0"
        ).fetchone()
        return row[0] if row else 0

    def get_unread_alerts(self) -> list:
        """获取所有未读告警，用于告警弹窗展示"""
        return self.conn.execute(
            "SELECT * FROM alert_logs WHERE is_read = 0 ORDER BY timestamp DESC"
        ).fetchall()

    def mark_alerts_read(self):
        """将所有未读告警标为已读（用户点击查看后调用）"""
        with self._lock:
            self.conn.execute("UPDATE alert_logs SET is_read = 1 WHERE is_read = 0")
            self.conn.commit()

    # ──────────────────────────────────────────────────────────
    #  获取所有害虫种类（HistoryWidget 下拉筛选框用）
    # ──────────────────────────────────────────────────────────
    def get_pest_classes(self) -> list[str]:
        """返回数据库中出现过的害虫种类列表"""
        rows = self.conn.execute(
            "SELECT DISTINCT pest_class FROM detections ORDER BY pest_class"
        ).fetchall()
        return [r[0] for r in rows]

    # ──────────────────────────────────────────────────────────
    #  清理：删除超期记录（每次启动或每日触发一次）
    # ──────────────────────────────────────────────────────────
    def cleanup_old_records(self, days: int = config.RETAIN_DAYS):
        """
        删除超过 days 天的检测记录和告警记录。
        注意：截图文件由 CaptureManager 另行清理，此处只清库记录。
        """
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            det_cur = self.conn.execute(
                "DELETE FROM detections WHERE timestamp < ?", (cutoff,)
            )
            alt_cur = self.conn.execute(
                "DELETE FROM alert_logs WHERE timestamp < ?", (cutoff,)
            )
            self.conn.commit()
        log.info(f"清理超期记录：detections 删除 {det_cur.rowcount} 条，"
                 f"alert_logs 删除 {alt_cur.rowcount} 条（cutoff={cutoff}）")

    # ──────────────────────────────────────────────────────────
    #  关闭连接（MainWindow.closeEvent 中调用）
    # ──────────────────────────────────────────────────────────
    def close(self):
        try:
            self.conn.close()
            log.info("数据库连接已关闭")
        except Exception as e:
            log.warning(f"关闭数据库时异常：{e}")