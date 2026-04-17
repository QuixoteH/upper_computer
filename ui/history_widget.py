# =============================================================
#  ui/history_widget.py  —  历史检测记录查询页
#  职责：
#    1. 提供日期区间 + 虫种类型两维度筛选
#    2. 在 QTableWidget 中分页展示查询结果
#    3. 支持将当前查询结果导出为 CSV 文件
#    4. 点击截图路径列可预览截图
#  嵌入 MainWindow 底部 Tab 区域，高度固定 240px
# =============================================================

import os
import csv
import logging
from datetime import datetime, timedelta

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QDateEdit, QComboBox, QHeaderView, QFileDialog,
    QSizePolicy, QAbstractItemView, QMessageBox
)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui  import QColor, QDesktopServices
from PyQt5.QtCore import QUrl

from db.database import Database

log = logging.getLogger(__name__)

# 表格列定义（索引, 标题, 宽度策略）
_COLUMNS = [
    (0, "ID",       50,  QHeaderView.Fixed),
    (1, "时间",     150, QHeaderView.Fixed),
    (2, "害虫种类", 110, QHeaderView.Stretch),
    (3, "数量",      60, QHeaderView.Fixed),
    (4, "置信度",    75, QHeaderView.Fixed),
    (5, "截图路径", 180, QHeaderView.Stretch),
]


class HistoryWidget(QWidget):
    """
    历史检测记录查询控件，嵌入主窗口底部 Tab。
    """

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._current_rows: list = []   # 当前查询结果缓存，供 export_csv() 使用

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        layout.addLayout(self._build_filter_bar())
        layout.addWidget(self._build_table())
        layout.addLayout(self._build_bottom_bar())

        # 初始加载最近 30 天数据
        self._do_query()

    # ──────────────────────────────────────────────────────────
    #  筛选栏构建
    # ──────────────────────────────────────────────────────────
    def _build_filter_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)

        # 起始日期
        bar.addWidget(QLabel("从："))
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDisplayFormat("yyyy-MM-dd")
        self._date_from.setDate(
            QDate.currentDate().addDays(-30)   # 默认最近 30 天
        )
        self._date_from.setFixedWidth(115)
        bar.addWidget(self._date_from)

        # 结束日期
        bar.addWidget(QLabel("至："))
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDisplayFormat("yyyy-MM-dd")
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setFixedWidth(115)
        bar.addWidget(self._date_to)

        # 虫种筛选
        bar.addWidget(QLabel("害虫："))
        self._combo_pest = QComboBox()
        self._combo_pest.setFixedWidth(120)
        self._combo_pest.setToolTip("按害虫种类筛选，选择「全部」查看所有记录")
        self._refresh_pest_combo()
        bar.addWidget(self._combo_pest)

        # 查询按钮
        btn_query = QPushButton("🔍 查询")
        btn_query.setFixedWidth(75)
        btn_query.clicked.connect(self._do_query)
        bar.addWidget(btn_query)

        # 刷新虫种下拉（数据库有新虫种时手动刷新）
        btn_refresh = QPushButton("↻")
        btn_refresh.setFixedWidth(30)
        btn_refresh.setToolTip("刷新害虫种类列表")
        btn_refresh.clicked.connect(self._refresh_pest_combo)
        bar.addWidget(btn_refresh)

        bar.addStretch()
        return bar

    # ──────────────────────────────────────────────────────────
    #  表格构建
    # ──────────────────────────────────────────────────────────
    def _build_table(self) -> QTableWidget:
        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([c[1] for c in _COLUMNS])

        # 列宽策略
        header = self._table.horizontalHeader()
        for idx, _, width, mode in _COLUMNS:
            if mode == QHeaderView.Fixed:
                self._table.setColumnWidth(idx, width)
            header.setSectionResizeMode(idx, mode)

        # 表格行为设置
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # 只读
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)  # 整行选中
        self._table.setAlternatingRowColors(True)                       # 交替行色
        self._table.verticalHeader().setVisible(False)                  # 隐藏行号
        self._table.setWordWrap(False)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 双击截图路径列打开图片
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        return self._table

    # ──────────────────────────────────────────────────────────
    #  底部状态栏
    # ──────────────────────────────────────────────────────────
    def _build_bottom_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()

        self._lbl_result_count = QLabel("共 0 条记录")
        self._lbl_result_count.setStyleSheet("color: #666; font-size: 11px;")
        bar.addWidget(self._lbl_result_count)

        bar.addStretch()

        # 导出 CSV 按钮（也是 main_window 菜单项的调用目标）
        self._btn_export = QPushButton("📤 导出 CSV")
        self._btn_export.setFixedWidth(100)
        self._btn_export.setEnabled(False)
        self._btn_export.setToolTip("将当前查询结果导出为 CSV 文件")
        self._btn_export.clicked.connect(self.export_csv)
        bar.addWidget(self._btn_export)

        return bar

    # ──────────────────────────────────────────────────────────
    #  刷新虫种下拉框（数据库 → ComboBox）
    # ──────────────────────────────────────────────────────────
    def _refresh_pest_combo(self):
        """从数据库读取所有出现过的虫种，更新下拉框（保留当前选中项）"""
        current = self._combo_pest.currentText() \
            if self._combo_pest.count() > 0 else "全部害虫"

        self._combo_pest.clear()
        self._combo_pest.addItem("全部害虫")

        try:
            classes = self.db.get_pest_classes()
            for cls in classes:
                self._combo_pest.addItem(cls)
        except Exception as e:
            log.warning(f"加载虫种列表失败：{e}")

        # 恢复之前的选中项
        idx = self._combo_pest.findText(current)
        if idx >= 0:
            self._combo_pest.setCurrentIndex(idx)

    # ──────────────────────────────────────────────────────────
    #  执行查询
    # ──────────────────────────────────────────────────────────
    def _do_query(self):
        """读取筛选条件，查询数据库，刷新表格"""
        date_from = self._date_from.date().toString("yyyy-MM-dd")
        date_to   = self._date_to.date().toString("yyyy-MM-dd")

        # 日期合法性校验
        if self._date_from.date() > self._date_to.date():
            QMessageBox.warning(
                self, "日期错误",
                "起始日期不能晚于结束日期，请重新选择"
            )
            return

        pest_class = self._combo_pest.currentText()
        if pest_class == "全部害虫":
            pest_class = None

        try:
            rows = self.db.query_detections(
                date_from  = date_from,
                date_to    = date_to,
                pest_class = pest_class,
            )
        except Exception as e:
            log.error(f"查询历史记录失败：{e}")
            QMessageBox.critical(self, "查询失败", f"数据库查询出错：{e}")
            return

        self._current_rows = rows
        self._fill_table(rows)
        self._lbl_result_count.setText(f"共 {len(rows)} 条记录")
        self._btn_export.setEnabled(len(rows) > 0)
        log.debug(f"历史查询完成：{len(rows)} 条  "
                  f"[{date_from} ~ {date_to}]  pest={pest_class}")

    # ──────────────────────────────────────────────────────────
    #  填充表格
    # ──────────────────────────────────────────────────────────
    def _fill_table(self, rows: list):
        self._table.setRowCount(0)   # 清空旧数据

        for row_data in rows:
            row_idx = self._table.rowCount()
            self._table.insertRow(row_idx)

            # 各列数据
            cells = [
                str(row_data["id"]),
                str(row_data["timestamp"]),
                str(row_data["pest_class"]),
                str(row_data["count"]),
                f"{row_data['confidence']:.1%}",
                str(row_data["capture_path"] or "—"),
            ]

            for col_idx, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)

                # 置信度列：颜色区分
                if col_idx == 4:
                    conf = row_data["confidence"]
                    if conf >= 0.75:
                        item.setForeground(QColor("#2e7d32"))
                    elif conf >= 0.55:
                        item.setForeground(QColor("#c05c00"))
                    else:
                        item.setForeground(QColor("#c62828"))

                # 截图路径列：有文件则显示为蓝色可点击样式
                if col_idx == 5 and row_data["capture_path"]:
                    item.setForeground(QColor("#1a5fa8"))
                    item.setToolTip("双击打开截图文件")

                self._table.setItem(row_idx, col_idx, item)

    # ──────────────────────────────────────────────────────────
    #  双击单元格：打开截图
    # ──────────────────────────────────────────────────────────
    def _on_cell_double_clicked(self, row: int, col: int):
        """双击截图路径列时，用系统默认程序打开图片"""
        if col != 5:
            return
        item = self._table.item(row, col)
        if item is None or item.text() == "—":
            return

        path = item.text()
        if not os.path.exists(path):
            QMessageBox.warning(
                self, "文件不存在",
                f"截图文件已被删除或移动：\n{path}"
            )
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))
        log.debug(f"打开截图：{path}")

    # ──────────────────────────────────────────────────────────
    #  对外接口：导出 CSV（MainWindow 菜单也会调用此方法）
    # ──────────────────────────────────────────────────────────
    def export_csv(self):
        """
        将 _current_rows 导出为 CSV。
        文件名默认含查询日期区间，弹出另存为对话框让用户选择路径。
        """
        if not self._current_rows:
            QMessageBox.information(
                self, "无数据",
                "当前查询结果为空，请先执行查询再导出"
            )
            return

        # 生成默认文件名
        date_from = self._date_from.date().toString("yyyyMMdd")
        date_to   = self._date_to.date().toString("yyyyMMdd")
        default_name = f"pest_records_{date_from}_{date_to}.csv"

        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出检测记录",
            default_name,
            "CSV 文件 (*.csv);;所有文件 (*)"
        )
        if not path:
            return   # 用户取消

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                # utf-8-sig：带 BOM，Excel 直接打开中文不乱码
                writer = csv.writer(f)
                writer.writerow(["ID", "时间", "害虫种类", "数量", "置信度", "截图路径"])
                for row in self._current_rows:
                    writer.writerow([
                        row["id"],
                        row["timestamp"],
                        row["pest_class"],
                        row["count"],
                        f"{row['confidence']:.4f}",
                        row["capture_path"] or "",
                    ])
            log.info(f"CSV 导出成功：{path}  共 {len(self._current_rows)} 条")
            QMessageBox.information(
                self, "导出成功",
                f"已导出 {len(self._current_rows)} 条记录\n{path}"
            )
        except OSError as e:
            log.error(f"CSV 导出失败：{e}")
            QMessageBox.critical(self, "导出失败", f"写入文件时出错：\n{e}")