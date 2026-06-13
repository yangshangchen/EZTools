import sys, os, re, json, time, shutil
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QCheckBox, QSpinBox, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QGroupBox, QSplitter, QScrollArea,
    QAbstractItemView, QFrame, QProgressBar, QGridLayout
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QColor, QBrush, QFont

# ============================================================
# Constants
# ============================================================
APP_NAME = "批量重命名工具"
CONFIG_FILE = Path.home() / ".batch_rename_config.json"
LOG_DIR = Path.home() / ".batch_rename_logs"

# ============================================================
# Helpers
# ============================================================
def safe_name(path):
    return Path(path).name

def ensure_dir(d):
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# File Scanner
# ============================================================
def scan_items(paths, recursive=True):
    items = []
    for p in paths:
        p = Path(p)
        if not p.exists():
            continue
        if p.is_file():
            items.append(str(p.resolve()))
        elif p.is_dir():
            try:
                for entry in os.scandir(str(p)):
                    if entry.is_file(follow_symlinks=False):
                        items.append(entry.path)
                    elif recursive and entry.is_dir(follow_symlinks=False):
                        items.extend(scan_items([entry.path], True))
            except PermissionError:
                pass
    return items

# ============================================================
# Rename Engine
# ============================================================
class RenameEngine:
    @staticmethod
    def generate(items, rules):
        results = []
        name_map = defaultdict(list)
        now = datetime.now()

        for idx, src in enumerate(items):
            p = Path(src)
            stem = p.stem
            ext = p.suffix
            new = p.name

            for r in rules:
                t = r.get("type")
                if t == "prefix_suffix":
                    pre = r.get("prefix", "")
                    suf = r.get("suffix", "")
                    new = pre + new + suf
                elif t == "sequential":
                    base = r.get("base_name", "").strip()
                    start = r.get("start", 1)
                    pad = r.get("padding", 3)
                    label = str(idx + start).zfill(pad)
                    name_part = base if base else stem
                    new = f"{name_part}_{label}{ext}"
                elif t == "find_replace":
                    find = r.get("find", "")
                    repl = r.get("replace", "")
                    use_re = r.get("regex", False)
                    if find:
                        if use_re:
                            try:
                                new = re.sub(find, repl, new)
                            except re.error:
                                pass
                        else:
                            new = new.replace(find, repl)
                elif t == "date_prefix":
                    dt_format = r.get("format", "%Y-%m-%d")
                    try:
                        mtime = os.path.getmtime(src)
                        dt = datetime.fromtimestamp(mtime)
                    except:
                        dt = now
                    date_str = dt.strftime(dt_format)
                    pad = r.get("padding", 3)
                    label = str(idx + 1).zfill(pad)
                    new = f"{date_str}_{label}{ext}"
                elif t == "delete_chars":
                    pos = r.get("position", 0)
                    count = r.get("count", 1)
                    name_without_ext = Path(new).stem
                    ext_part = Path(new).suffix
                    if 0 <= pos < len(name_without_ext):
                        new_name = name_without_ext[:pos] + name_without_ext[pos + count:]
                        new = new_name + ext_part

            target_path = str(p.parent / new)
            src_size = 0
            try:
                src_size = os.path.getsize(src)
            except:
                pass
            src_mtime = 0
            try:
                src_mtime = os.path.getmtime(src)
            except:
                pass

            results.append({
                "src": src,
                "src_name": p.name,
                "new_name": new,
                "target": target_path,
                "size": src_size,
                "mtime": src_mtime,
            })
            name_map[new].append(src)

        # Detect conflicts
        seen = {}
        for item in results:
            key = item["new_name"]
            if key in seen:
                item["conflict"] = "internal"
                seen[key]["conflict"] = "internal"
            elif os.path.exists(item["target"]):
                item["conflict"] = "exists"
            else:
                item["conflict"] = None
            seen[key] = item

        return results

# ============================================================
# Undo Manager
# ============================================================
class UndoManager:
    def __init__(self):
        ensure_dir(LOG_DIR)

    def save_log(self, operations):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = LOG_DIR / f"rename_{ts}.json"
        data = {
            "timestamp": ts,
            "operations": operations,
        }
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return str(log_path)

    def get_recent_logs(self, limit=10):
        logs = sorted(LOG_DIR.glob("rename_*.json"), reverse=True)
        return [str(l) for l in logs[:limit]]

    def undo_log(self, log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ops = data.get("operations", [])
        errors = []
        undone = 0
        for op in reversed(ops):
            src = op["new_path"]
            dst = op["orig_path"]
            if os.path.exists(src):
                try:
                    os.rename(src, dst)
                    undone += 1
                except Exception as e:
                    errors.append(f"{Path(src).name}: {e}")
            else:
                errors.append(f"{Path(src).name}: 源文件不存在")
        return undone, errors

# ============================================================
# Preview Worker (threaded)
# ============================================================
class PreviewWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, items, rules):
        super().__init__()
        self.items = items
        self.rules = rules

    def run(self):
        try:
            results = RenameEngine.generate(self.items, self.rules)
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


# ============================================================
# Main Window
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.items = []
        self.preview_results = []
        self.last_log_path = None
        self.undo_mgr = UndoManager()
        self.preview_worker = None
        self.init_ui()
        self.apply_styles()

    def init_ui(self):
        self.setWindowTitle(APP_NAME)
        self.resize(900, 620)
        self.setMinimumSize(750, 500)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # ===== Top bar =====
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)
        self.btn_add_files = QPushButton("添加文件")
        self.btn_add_folder = QPushButton("添加文件夹")
        self.btn_clear = QPushButton("清空列表")
        self.lbl_count = QLabel("共 0 项")
        self.lbl_count.setObjectName("countLabel")
        top_bar.addWidget(self.btn_add_files)
        top_bar.addWidget(self.btn_add_folder)
        top_bar.addWidget(self.btn_clear)
        top_bar.addStretch()
        top_bar.addWidget(self.lbl_count)
        main_layout.addLayout(top_bar)

        # ===== Main splitter =====
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)

        # --- Left: File list ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 5, 0)
        title_left = QLabel("文件列表")
        title_left.setObjectName("sectionTitle")
        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        left_layout.addWidget(title_left)
        left_layout.addWidget(self.file_list)

        # --- Right: Rules + Preview ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 0, 0, 0)
        right_layout.setSpacing(8)

        # Rules scroll area
        rules_scroll = QScrollArea()
        rules_scroll.setWidgetResizable(True)
        rules_scroll.setFrameShape(QFrame.NoFrame)
        rules_container = QWidget()
        rules_layout = QVBoxLayout(rules_container)
        rules_layout.setSpacing(8)
        rules_layout.setContentsMargins(0, 0, 0, 0)

        title_rules = QLabel("重命名规则")
        title_rules.setObjectName("sectionTitle")
        rules_layout.addWidget(title_rules)

        # Rule 1: Prefix / Suffix
        g1 = QGroupBox("① 添加前缀 / 后缀")
        g1l = QHBoxLayout(g1)
        g1l.addWidget(QLabel("前缀:"))
        self.edit_prefix = QLineEdit()
        self.edit_prefix.setPlaceholderText("如: 公司文档_")
        g1l.addWidget(self.edit_prefix)
        g1l.addWidget(QLabel("后缀:"))
        self.edit_suffix = QLineEdit()
        self.edit_suffix.setPlaceholderText("如: _v2")
        g1l.addWidget(self.edit_suffix)
        rules_layout.addWidget(g1)

        # Rule 2: Sequential
        g2 = QGroupBox("② 序号命名")
        g2l = QGridLayout(g2)
        g2l.addWidget(QLabel("基础名称:"), 0, 0)
        self.edit_seq_name = QLineEdit()
        self.edit_seq_name.setPlaceholderText("留空使用原名")
        g2l.addWidget(self.edit_seq_name, 0, 1)
        g2l.addWidget(QLabel("起始:"), 0, 2)
        self.spin_seq_start = QSpinBox()
        self.spin_seq_start.setRange(1, 99999)
        self.spin_seq_start.setValue(1)
        g2l.addWidget(self.spin_seq_start, 0, 3)
        g2l.addWidget(QLabel("位数:"), 1, 0)
        self.spin_seq_pad = QSpinBox()
        self.spin_seq_pad.setRange(1, 10)
        self.spin_seq_pad.setValue(3)
        g2l.addWidget(self.spin_seq_pad, 1, 1)
        rules_layout.addWidget(g2)

        # Rule 3: Find & Replace
        g3 = QGroupBox("③ 查找替换")
        g3l = QGridLayout(g3)
        g3l.addWidget(QLabel("查找:"), 0, 0)
        self.edit_find = QLineEdit()
        self.edit_find.setPlaceholderText("要查找的文本")
        g3l.addWidget(self.edit_find, 0, 1)
        g3l.addWidget(QLabel("替换为:"), 0, 2)
        self.edit_replace = QLineEdit()
        self.edit_replace.setPlaceholderText("替换后的文本")
        g3l.addWidget(self.edit_replace, 0, 3)
        self.chk_regex = QCheckBox("正则表达式")
        g3l.addWidget(self.chk_regex, 1, 1, 1, 3)
        rules_layout.addWidget(g3)

        # Rule 4: Date prefix
        g4 = QGroupBox("④ 按修改日期命名")
        g4l = QHBoxLayout(g4)
        g4l.addWidget(QLabel("日期格式:"))
        self.combo_date = QComboBox()
        self.combo_date.addItems([
            "%Y-%m-%d", "%Y%m%d", "%Y-%m-%d_%H%M%S",
            "%y%m%d", "%Y年%m月%d日",
        ])
        self.combo_date.setEditable(True)
        g4l.addWidget(self.combo_date)
        g4l.addWidget(QLabel("序号位数:"))
        self.spin_date_pad = QSpinBox()
        self.spin_date_pad.setRange(1, 10)
        self.spin_date_pad.setValue(3)
        g4l.addWidget(self.spin_date_pad)
        rules_layout.addWidget(g4)

        # Rule 5: Delete chars
        g5 = QGroupBox("⑤ 删除指定字符")
        g5l = QHBoxLayout(g5)
        g5l.addWidget(QLabel("起始位置:"))
        self.spin_del_pos = QSpinBox()
        self.spin_del_pos.setRange(0, 999)
        self.spin_del_pos.setValue(0)
        g5l.addWidget(self.spin_del_pos)
        g5l.addWidget(QLabel("删除数量:"))
        self.spin_del_count = QSpinBox()
        self.spin_del_count.setRange(1, 999)
        self.spin_del_count.setValue(1)
        g5l.addWidget(self.spin_del_count)
        rules_layout.addWidget(g5)

        # Preview button
        self.btn_preview = QPushButton("应用规则 - 生成预览")
        self.btn_preview.setObjectName("previewBtn")
        rules_layout.addWidget(self.btn_preview)

        rules_scroll.setWidget(rules_container)
        right_layout.addWidget(rules_scroll, stretch=1)

        # ===== Preview Section =====
        preview_header = QHBoxLayout()
        preview_header.setSpacing(8)
        lbl_preview = QLabel("预览")
        lbl_preview.setObjectName("sectionTitle")
        self.lbl_stats = QLabel("")
        self.lbl_stats.setObjectName("statsLabel")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(16)
        preview_header.addWidget(lbl_preview)
        preview_header.addWidget(self.lbl_stats)
        preview_header.addStretch()
        preview_header.addWidget(self.progress_bar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["原文件名", "新文件名", "大小", "状态"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)

        # Action buttons
        action_bar = QHBoxLayout()
        action_bar.setSpacing(6)
        self.btn_execute = QPushButton("执行重命名")
        self.btn_execute.setObjectName("executeBtn")
        self.btn_execute.setEnabled(False)
        self.btn_undo = QPushButton("撤销上次")
        self.btn_undo.setObjectName("undoBtn")
        self.btn_undo.setEnabled(False)
        self.btn_export_log = QPushButton("导出日志")
        self.btn_export_log.setObjectName("logBtn")
        self.chk_top = QCheckBox("总在最前")
        action_bar.addWidget(self.btn_execute)
        action_bar.addWidget(self.btn_undo)
        action_bar.addWidget(self.btn_export_log)
        action_bar.addStretch()
        action_bar.addWidget(self.chk_top)

        right_layout.addLayout(preview_header)
        right_layout.addWidget(self.table, stretch=2)
        right_layout.addLayout(action_bar)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        main_layout.addWidget(splitter)

        # ===== Connections =====
        self.btn_add_files.clicked.connect(self.add_files)
        self.btn_add_folder.clicked.connect(self.add_folder)
        self.btn_clear.clicked.connect(self.clear_items)
        self.btn_preview.clicked.connect(self.start_preview)
        self.btn_execute.clicked.connect(self.execute_rename)
        self.btn_undo.clicked.connect(self.undo_last)
        self.btn_export_log.clicked.connect(self.export_log)
        self.chk_top.stateChanged.connect(self.toggle_top)

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #F5F5F5; font-family: "Segoe UI", "Microsoft YaHei"; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; color: #111; }
            QLabel#sectionTitle { param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; font-weight: 700; color: #111; padding-bottom: 2px; }
            QLabel#countLabel { param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; color: #333; padding: 0 8px; }
            QLabel#statsLabel { param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; color: #333; }
            QPushButton { background: #FFF; border: 1px solid #CCCCCC; border-radius: 4px; padding: 5px 14px; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; font-weight: 600; }
            QPushButton:hover { background: #E8E8E8; border-color: #0078D4; }
            QPushButton:disabled { color: #666; background: #F0F0F0; border-color: #DDD; }
            QPushButton#previewBtn { background: #0078D4; color: #FFF; border: none; padding: 8px; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; font-weight: 700; border-radius: 5px; }
            QPushButton#previewBtn:hover { background: #106EBE; }
            QPushButton#executeBtn { background: #2E7D32; color: #FFF; border: none; padding: 8px 20px; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; font-weight: 700; border-radius: 5px; }
            QPushButton#executeBtn:hover { background: #1B5E20; }
            QPushButton#executeBtn:disabled { background: #A5D6A7; color: #DDD; }
            QPushButton#undoBtn { param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; }
            QPushButton#logBtn { param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; }
            QListWidget { background: #FFF; border: 1px solid #D0D0D0; border-radius: 5px; padding: 2px; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; }
            QListWidget::item { padding: 3px 6px; border-radius: 2px; }
            QListWidget::item:selected { background: #0078D4; color: #FFF; }
            QGroupBox { font-weight: 700; border: 1px solid #D0D0D0; border-radius: 6px; margin-top: 8px; padding: 14px 8px 8px 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #111; }
            QLineEdit { background: #FFF; border: 1px solid #D0D0D0; border-radius: 3px; padding: 4px 6px; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; }
            QLineEdit:focus { border-color: #0078D4; }
            QSpinBox { background: #FFF; border: 1px solid #D0D0D0; border-radius: 3px; padding: 3px 4px; }
            QComboBox { background: #FFF; border: 1px solid #D0D0D0; border-radius: 3px; padding: 3px 6px; }
            QTableWidget { background: #FFF; border: 1px solid #D0D0D0; border-radius: 5px; gridline-color: #E8E8E8; }
            QTableWidget::item { padding: 2px 6px; }
            QHeaderView::section { background: #F0F0F0; color: #111; font-weight: 600; border: none; border-bottom: 1px solid #D0D0D0; padding: 4px 8px; }
            QProgressBar { border: 1px solid #D0D0D0; border-radius: 3px; text-align: center; color: #111; background: #FFF; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; }
            QProgressBar::chunk { background: #0078D4; border-radius: 2px; }
            QCheckBox { spacing: 6px; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; font-weight: 600; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 2px solid #B0B0B0; border-radius: 3px; }
            QCheckBox::indicator:checked { background: #0078D4; border-color: #0078D4; }
            QScrollArea { border: none; }
            QSplitter::handle { background: #E0E0E0; }
        """)

    # ---- File Management ----
    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择文件")
        if paths:
            self._add_paths(paths)

    def add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if path:
            items = scan_items([path], recursive=True)
            self._add_paths(items)

    def _add_paths(self, paths):
        existing = set(self.items)
        added = 0
        for p in paths:
            if p not in existing:
                self.items.append(p)
                self.file_list.addItem(Path(p).name)
                existing.add(p)
                added += 1
        self._update_counts()

    def clear_items(self):
        self.items.clear()
        self.file_list.clear()
        self.preview_results = []
        self.table.setRowCount(0)
        self.btn_execute.setEnabled(False)
        self._update_counts()

    def _update_counts(self):
        self.lbl_count.setText(f"共 {len(self.items)} 项")
        self.btn_clear.setEnabled(len(self.items) > 0)

    # ---- Toggle Top ----
    def toggle_top(self, state):
        flags = self.windowFlags()
        if state == Qt.Checked:
            self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
        self.show()

    # ---- Preview ----
    def start_preview(self):
        if not self.items:
            QMessageBox.warning(self, "提示", "请先添加文件")
            return

        rules = self._collect_rules()
        self.btn_preview.setEnabled(False)
        self.btn_preview.setText("正在生成预览...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.table.setRowCount(0)

        self.preview_worker = PreviewWorker(list(self.items), rules)
        self.preview_worker.finished.connect(self._on_preview_done)
        self.preview_worker.error.connect(self._on_preview_error)
        self.preview_worker.start()

    def _collect_rules(self):
        rules = []
        prefix = self.edit_prefix.text().strip()
        suffix = self.edit_suffix.text().strip()
        if prefix or suffix:
            rules.append({"type": "prefix_suffix", "prefix": prefix, "suffix": suffix})

        seq_name = self.edit_seq_name.text().strip()
        rules.append({
            "type": "sequential",
            "base_name": seq_name,
            "start": self.spin_seq_start.value(),
            "padding": self.spin_seq_pad.value(),
        })

        find_text = self.edit_find.text()
        if find_text:
            rules.append({
                "type": "find_replace",
                "find": find_text,
                "replace": self.edit_replace.text(),
                "regex": self.chk_regex.isChecked(),
            })

        rules.append({
            "type": "date_prefix",
            "format": self.combo_date.currentText(),
            "padding": self.spin_date_pad.value(),
        })

        del_count = self.spin_del_count.value()
        if del_count > 0:
            rules.append({
                "type": "delete_chars",
                "position": self.spin_del_pos.value(),
                "count": del_count,
            })

        return rules

    def _on_preview_done(self, results):
        self.preview_results = results
        self.progress_bar.setVisible(False)
        self.btn_preview.setEnabled(True)
        self.btn_preview.setText("应用规则 - 生成预览")

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(results))

        conflict_count = 0
        ok_count = 0

        for row, r in enumerate(results):
            src_item = QTableWidgetItem(r["src_name"])
            src_item.setData(Qt.UserRole, r["src"])
            self.table.setItem(row, 0, src_item)

            new_item = QTableWidgetItem(r["new_name"])
            self.table.setItem(row, 1, new_item)

            try:
                size = os.path.getsize(r["src"])
                size_text = f"{size/1024:.1f} KB" if size < 1048576 else f"{size/1048576:.1f} MB"
            except:
                size_text = "-"
            self.table.setItem(row, 2, QTableWidgetItem(size_text))

            if r.get("conflict") == "internal":
                status = "重复"
                color = QColor("#D32F2F")
                conflict_count += 1
            elif r.get("conflict") == "exists":
                status = "文件已存在"
                color = QColor("#E65100")
                conflict_count += 1
            else:
                status = "正常"
                color = QColor("#2E7D32")
                ok_count += 1

            status_item = QTableWidgetItem(status)
            status_item.setForeground(QBrush(color))
            status_item.setFont(QFont("Segoe UI", 14, QFont.Bold))
            self.table.setItem(row, 3, status_item)

            if r.get("conflict"):
                for col in range(3):
                    self.table.item(row, col).setBackground(QBrush(QColor("#FFF3E0")))

        self.table.setSortingEnabled(True)

        total = len(results)
        self.lbl_stats.setText(f"共 {total} 项 | ✅ {ok_count} 正常 | ⚠️ {conflict_count} 冲突")
        self.btn_execute.setEnabled(total > 0 and conflict_count == 0)

        if conflict_count > 0:
            QMessageBox.warning(self, "冲突检测",
                f"发现 {conflict_count} 个命名冲突，请修改规则后重新预览。\n\n"
                "冲突原因：\n"
                "- 多个文件将重命名为相同名称 (重复)\n"
                "- 目标文件名已存在于当前目录 (文件已存在)")

    def _on_preview_error(self, msg):
        self.progress_bar.setVisible(False)
        self.btn_preview.setEnabled(True)
        self.btn_preview.setText("应用规则 - 生成预览")
        QMessageBox.critical(self, "错误", f"生成预览失败:\n{msg}")

    # ---- Execute ----
    def execute_rename(self):
        if not self.preview_results:
            return

        has_conflicts = any(r.get("conflict") for r in self.preview_results)
        if has_conflicts:
            reply = QMessageBox.question(self, "确认",
                "存在命名冲突的文件将被跳过，是否继续？",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        operations = []
        errors = []
        renamed = 0
        skipped = 0

        self.btn_execute.setEnabled(False)
        self.btn_execute.setText("正在执行...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(self.preview_results))
        self.progress_bar.setValue(0)
        QApplication.processEvents()

        for i, r in enumerate(self.preview_results):
            self.progress_bar.setValue(i + 1)
            self.progress_bar.setFormat(f"正在处理: {r['src_name']}  ({i+1}/{len(self.preview_results)})")
            QApplication.processEvents()

            if r.get("conflict"):
                skipped += 1
                continue

            src = r["src"]
            dst = r["target"]

            if src == dst:
                skipped += 1
                continue

            try:
                os.rename(src, dst)
                operations.append({"orig_path": src, "new_path": dst})
                renamed += 1
            except PermissionError:
                errors.append(f"{r['src_name']}: 权限不足")
            except OSError as e:
                errors.append(f"{r['src_name']}: {e}")

        self.progress_bar.setVisible(False)
        self.btn_execute.setText("执行重命名")

        # Save log
        if operations:
            self.last_log_path = self.undo_mgr.save_log(operations)
            self.btn_undo.setEnabled(True)
            self.btn_export_log.setEnabled(True)

        # Summary
        parts = [f"成功重命名: {renamed} 个文件"]
        if skipped:
            parts.append(f"跳过: {skipped} 个")
        if errors:
            parts.append(f"\n\n错误:\n" + "\n".join(errors[:10]))
            if len(errors) > 10:
                parts.append(f"...及其他 {len(errors)-10} 项")
        QMessageBox.information(self, "执行完成", "\n".join(parts))

        # Refresh preview
        self.preview_results = []
        self.table.setRowCount(0)
        self.btn_execute.setEnabled(False)

    # ---- Undo ----
    def undo_last(self):
        logs = self.undo_mgr.get_recent_logs(1)
        if not logs:
            QMessageBox.information(self, "提示", "没有可撤销的操作")
            return

        log_path = logs[0]
        reply = QMessageBox.question(self, "确认撤销",
            f"将撤销以下操作:\n{log_path}\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        undone, errors = self.undo_mgr.undo_log(log_path)
        msg = f"已撤销 {undone} 个文件的重命名"
        if errors:
            msg += f"\n\n以下文件撤销失败:\n" + "\n".join(errors[:5])
        QMessageBox.information(self, "撤销完成", msg)
        self.btn_undo.setEnabled(False)

    # ---- Export Log ----
    def export_log(self):
        logs = self.undo_mgr.get_recent_logs(50)
        if not logs:
            QMessageBox.information(self, "提示", "没有日志可导出")
            return

        save_path, _ = QFileDialog.getSaveFileName(self, "保存日志", "rename_log.txt", "文本文件 (*.txt)")
        if not save_path:
            return

        try:
            with open(save_path, "w", encoding="utf-8") as out:
                out.write("批量重命名操作日志\n")
                out.write("=" * 60 + "\n\n")
                for log_path in logs:
                    out.write(f"操作时间: {Path(log_path).stem.replace('rename_', '')}\n")
                    with open(log_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    for op in data.get("operations", []):
                        out.write(f"  {op['orig_path']}  →  {op['new_path']}\n")
                    out.write("\n")
            QMessageBox.information(self, "成功", f"日志已导出到:\n{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {e}")


# ============================================================
# Entry
# ============================================================
if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("batchrenamer")
    except:
        pass
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
