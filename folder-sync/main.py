import sys, os, hashlib, time, shutil
from pathlib import Path
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QCheckBox, QRadioButton, QButtonGroup,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox, QGroupBox,
    QSplitter, QFrame, QProgressBar, QTextEdit, QAbstractItemView, QGridLayout
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QTextCursor

# ============================================================
# Constants
# ============================================================
CHUNK_SIZE = 64 * 1024  # 64KB for MD5

# ============================================================
# Helpers
# ============================================================
def fmt_size(b):
    if b < 1024:
        return f"{b} B"
    if b < 1048576:
        return f"{b/1024:.1f} KB"
    return f"{b/1048576:.2f} MB"

def md5_file(path):
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except PermissionError:
        return None
    except Exception:
        return None

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# Exclusion Rules
# ============================================================
def should_exclude(name, rel_path, exclude_dirs, exclude_exts):
    name_lower = name.lower()
    for d in exclude_dirs:
        if d.strip() and d.strip() in rel_path.parts:
            return True
    for e in exclude_exts:
        e = e.strip().lower()
        if not e:
            continue
        if e.startswith("."):
            if name_lower.endswith(e):
                return True
        elif name_lower == e.lower():
            return True
    return False


# ============================================================
# Scan
# ============================================================
def scan_dir(root, exclude_dirs, exclude_exts):
    items = {}
    root = Path(root).resolve()
    try:
        for entry in os.scandir(str(root)):
            name = entry.name
            rel = Path(name)
            if should_exclude(name, rel, exclude_dirs, exclude_exts):
                continue
            if entry.is_file(follow_symlinks=False):
                try:
                    st = entry.stat()
                    items[str(rel)] = {
                        "path": entry.path,
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                        "is_dir": False,
                    }
                except:
                    pass
            elif entry.is_dir(follow_symlinks=False):
                items[str(rel)] = {
                    "path": entry.path,
                    "size": 0,
                    "mtime": 0,
                    "is_dir": True,
                }
                sub = scan_dir(entry.path, exclude_dirs, exclude_exts)
                for k, v in sub.items():
                    items[f"{name}/{k}"] = v
    except PermissionError:
        pass
    return items


# ============================================================
# Sync Engine
# ============================================================
class SyncEngine:
    @staticmethod
    def compare(src_items, dst_items, mode="mirror", use_md5=False):
        ops = []
        src_keys = set(src_items.keys())
        dst_keys = set(dst_items.keys())

        # Files to copy / update (in source)
        for key in sorted(src_keys):
            s = src_items[key]
            if s["is_dir"]:
                if key not in dst_items:
                    ops.append({"type": "mkdir", "key": key, "path": s["path"]})
                continue
            if key in dst_items:
                d = dst_items[key]
                if s["size"] == d["size"] and s["mtime"] == d["mtime"]:
                    continue
                if use_md5:
                    s_md5 = md5_file(s["path"])
                    d_md5 = md5_file(d["path"])
                    if s_md5 is not None and d_md5 is not None and s_md5 == d_md5:
                        continue
                ops.append({"type": "update", "key": key, "src": s["path"], "size": s["size"]})
            else:
                ops.append({"type": "copy", "key": key, "src": s["path"], "size": s["size"]})

        # Files to delete (in dest but not in source) - mirror only
        if mode == "mirror":
            for key in sorted(dst_keys, reverse=True):
                if key not in src_keys:
                    d = dst_items[key]
                    ops.append({"type": "delete", "key": key, "path": d["path"], "is_dir": d["is_dir"]})

        return ops

    @staticmethod
    def execute_op(op, dst_root, log_callback):
        dst_root = Path(dst_root).resolve()
        dest_path = dst_root / op["key"]
        try:
            t = op["type"]
            if t == "mkdir":
                dest_path.mkdir(parents=True, exist_ok=True)
                log_callback(f"[{now_str()}] 创建目录: {op['key']}")
                return True
            elif t == "copy":
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(op["src"], str(dest_path))
                log_callback(f"[{now_str()}] 复制: {op['key']}  ({fmt_size(op['size'])})")
                return True
            elif t == "update":
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(op["src"], str(dest_path))
                log_callback(f"[{now_str()}] 更新: {op['key']}  ({fmt_size(op['size'])})")
                return True
            elif t == "delete":
                if op["is_dir"]:
                    shutil.rmtree(str(dest_path), ignore_errors=True)
                else:
                    os.remove(str(dest_path))
                log_callback(f"[{now_str()}] 删除: {op['key']}")
                return True
        except PermissionError:
            log_callback(f"[{now_str()}] 权限不足: {op['key']}")
        except OSError as e:
            log_callback(f"[{now_str()}] 错误: {op['key']}  - {e}")
        return False


# ============================================================
# Worker Thread
# ============================================================
class SyncWorker(QThread):
    progress = pyqtSignal(int, int)
    log = pyqtSignal(str)
    finished = pyqtSignal(int, int, int)

    def __init__(self, src, dst, mode, use_md5, exclude_dirs, exclude_exts, simulate=False):
        super().__init__()
        self.src = src
        self.dst = dst
        self.mode = mode
        self.use_md5 = use_md5
        self.exclude_dirs = exclude_dirs
        self.exclude_exts = exclude_exts
        self.simulate = simulate

    def run(self):
        self.log.emit(f"[{now_str()}] 开始扫描源文件夹: {self.src}")
        src_items = scan_dir(self.src, self.exclude_dirs, self.exclude_exts)
        self.log.emit(f"[{now_str()}] 源文件夹: {len(src_items)} 项")

        self.log.emit(f"[{now_str()}] 开始扫描目标文件夹: {self.dst}")
        dst_items = scan_dir(self.dst, self.exclude_dirs, self.exclude_exts) if os.path.exists(self.dst) else {}
        self.log.emit(f"[{now_str()}] 目标文件夹: {len(dst_items)} 项")

        ops = SyncEngine.compare(src_items, dst_items, self.mode, self.use_md5)

        if not ops:
            self.log.emit(f"[{now_str()}] 无需操作，文件已同步。")
            self.finished.emit(0, 0, 0)
            return

        to_copy = sum(1 for o in ops if o["type"] in ("copy", "update"))
        to_del = sum(1 for o in ops if o["type"] == "delete")
        to_mkdir = sum(1 for o in ops if o["type"] == "mkdir")
        total_bytes = sum(o.get("size", 0) for o in ops if o["type"] in ("copy", "update"))

        self.log.emit(f"[{now_str()}] 分析完成: 新建 {to_mkdir} | 复制/更新 {to_copy} | 删除 {to_del} | 总数据量 {fmt_size(total_bytes)}")

        if self.simulate:
            for o in ops:
                if o["type"] == "mkdir":
                    self.log.emit(f"  [创建目录] {o['key']}")
                elif o["type"] == "copy":
                    self.log.emit(f"  [复制] {o['key']}  ({fmt_size(o['size'])})")
                elif o["type"] == "update":
                    self.log.emit(f"  [更新] {o['key']}  ({fmt_size(o['size'])})")
                elif o["type"] == "delete":
                    self.log.emit(f"  [删除] {o['key']}")
            self.log.emit(f"[{now_str()}] 模拟完成。共 {len(ops)} 项操作。")
            self.finished.emit(to_copy, to_del, total_bytes)
            return

        # Execute
        total = len(ops)
        success = 0
        fail = 0
        copied_bytes = 0
        self.log.emit(f"[{now_str()}] 开始执行同步...")

        for i, o in enumerate(ops):
            self.progress.emit(i + 1, total)
            ok = SyncEngine.execute_op(o, self.dst, self.log.emit)
            if ok:
                success += 1
                copied_bytes += o.get("size", 0)
            else:
                fail += 1

        self.log.emit(f"[{now_str()}] 同步完成！成功 {success}，失败 {fail}，传输 {fmt_size(copied_bytes)}")
        self.finished.emit(success, fail, copied_bytes)


# ============================================================
# Main Window
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.init_ui()
        self.apply_styles()

    def init_ui(self):
        self.setWindowTitle("文件夹同步备份工具 v1.0")
        self.resize(850, 650)
        self.setMinimumSize(700, 500)

        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)
        ml.setContentsMargins(14, 14, 14, 14)
        ml.setSpacing(10)

        # ===== Path selectors =====
        def path_row(label):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            l = QLabel(label)
            l.setObjectName("pathLabel")
            edit = QLineEdit()
            edit.setObjectName("pathEdit")
            edit.setPlaceholderText("请选择文件夹...")
            btn = QPushButton("浏览")
            btn.setObjectName("browseBtn")
            btn.setFixedWidth(70)
            h.addWidget(l)
            h.addWidget(edit)
            h.addWidget(btn)
            return w, edit, btn

        self.src_row, self.edit_src, self.btn_src = path_row("源文件夹:")
        self.dst_row, self.edit_dst, self.btn_dst = path_row("目标文件夹:")
        ml.addWidget(self.src_row)
        ml.addWidget(self.dst_row)

        # ===== Mode + Exclusion =====
        mid = QHBoxLayout()
        mid.setSpacing(12)

        # Left: mode
        mg = QGroupBox("同步模式")
        mg.setObjectName("modeGroup")
        mv = QVBoxLayout(mg)
        mv.setSpacing(6)
        self.radio_mirror = QRadioButton("镜像同步 (目标与源完全一致，删除多余文件)")
        self.radio_inc = QRadioButton("增量备份 (仅复制新增/修改的文件)")
        self.radio_mirror.setChecked(True)
        self.mode_group = QButtonGroup()
        self.mode_group.addButton(self.radio_mirror)
        self.mode_group.addButton(self.radio_inc)
        self.chk_md5 = QCheckBox("使用 MD5 比较 (更准确，速度较慢)")
        self.chk_md5.setChecked(False)
        mv.addWidget(self.radio_mirror)
        mv.addWidget(self.radio_inc)
        mv.addWidget(self.chk_md5)
        mv.addStretch()

        # Right: exclusions
        eg = QGroupBox("排除规则")
        eg.setObjectName("exclGroup")
        ev = QVBoxLayout(eg)
        ev.setSpacing(4)
        self.excl_list = QListWidget()
        self.excl_list.setObjectName("exclList")
        default_excludes = [".tmp", ".log", "__pycache__", ".git", ".svn", ".DS_Store", "node_modules"]
        for e in default_excludes:
            self.excl_list.addItem(e)
        eb = QHBoxLayout()
        eb.setSpacing(4)
        self.btn_excl_add = QPushButton("添加")
        self.btn_excl_del = QPushButton("删除")
        self.btn_excl_add.setObjectName("smallBtn")
        self.btn_excl_del.setObjectName("smallBtn")
        eb.addWidget(self.btn_excl_add)
        eb.addWidget(self.btn_excl_del)
        ev.addWidget(self.excl_list)
        ev.addLayout(eb)

        mid.addWidget(mg, 2)
        mid.addWidget(eg, 1)
        ml.addLayout(mid)

        # ===== Stats =====
        stats_w = QWidget()
        stats_w.setObjectName("statsBar")
        sh = QHBoxLayout(stats_w)
        sh.setContentsMargins(4, 4, 4, 4)
        sh.setSpacing(16)
        self.lbl_src_count = QLabel("源: -")
        self.lbl_dst_count = QLabel("目标: -")
        self.lbl_src_size = QLabel("源大小: -")
        self.lbl_dst_size = QLabel("目标大小: -")
        for l in (self.lbl_src_count, self.lbl_dst_count, self.lbl_src_size, self.lbl_dst_size):
            l.setObjectName("statLabel")
        sh.addWidget(self.lbl_src_count)
        sh.addWidget(self.lbl_src_size)
        sh.addWidget(self.lbl_dst_count)
        sh.addWidget(self.lbl_dst_size)
        ml.addWidget(stats_w)

        # ===== Action buttons =====
        act = QHBoxLayout()
        act.setSpacing(8)
        self.btn_simulate = QPushButton("模拟")
        self.btn_simulate.setObjectName("simulateBtn")
        self.btn_execute = QPushButton("执行同步")
        self.btn_execute.setObjectName("executeBtn")
        self.btn_execute.setEnabled(False)
        self.btn_schedule = QPushButton("生成计划任务.bat")
        self.btn_schedule.setObjectName("scheduleBtn")
        self.pbar = QProgressBar()
        self.pbar.setObjectName("progressBar")
        self.pbar.setVisible(False)
        self.pbar.setFormat("")
        self.chk_top = QCheckBox("总在最前")
        self.chk_top.setObjectName("topCheck")
        act.addWidget(self.btn_simulate)
        act.addWidget(self.btn_execute)
        act.addWidget(self.btn_schedule)
        act.addWidget(self.pbar)
        act.addStretch()
        act.addWidget(self.chk_top)
        ml.addLayout(act)

        # ===== Log =====
        log_label = QLabel("操作日志:")
        log_label.setObjectName("logTitle")
        self.log_view = QTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 11))
        ml.addWidget(log_label)
        ml.addWidget(self.log_view, stretch=1)

        # ===== Connections =====
        self.btn_src.clicked.connect(lambda: self._browse(self.edit_src))
        self.btn_dst.clicked.connect(lambda: self._browse(self.edit_dst))
        self.edit_src.textChanged.connect(self._update_stats)
        self.edit_dst.textChanged.connect(self._update_stats)
        self.btn_simulate.clicked.connect(lambda: self.start_sync(simulate=True))
        self.btn_execute.clicked.connect(lambda: self.start_sync(simulate=False))
        self.btn_schedule.clicked.connect(self.gen_schedule)
        self.btn_excl_add.clicked.connect(self._add_excl)
        self.btn_excl_del.clicked.connect(self._del_excl)
        self.chk_top.stateChanged.connect(self._toggle_top)

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { font-family: "Segoe UI", "Microsoft YaHei", sans-serif; font-size: 14pt; color: #111; background: #FFFFFF; }
            QLabel#pathLabel { font-weight: 600; font-size: 14pt; min-width: 70px; color: #333; }
            QLineEdit#pathEdit { background: #FFF; border: 1px solid #D0D0D0; border-radius: 4px; padding: 6px 8px; font-size: 14pt; }
            QLineEdit#pathEdit:focus { border-color: #0078D4; }
            QPushButton#browseBtn { background: #FFF; border: 1px solid #D0D0D0; border-radius: 4px; padding: 6px 12px; font-size: 14pt; font-weight: 600; }
            QPushButton#browseBtn:hover { background: #E8E8E8; border-color: #0078D4; }
            QGroupBox { font-weight: 700; border: 1px solid #D0D0D0; border-radius: 6px; margin-top: 10px; padding: 18px 10px 10px 10px; background: #FFF; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; color: #111; }
            QRadioButton, QCheckBox { font-size: 14pt; spacing: 6px; }
            QRadioButton::indicator, QCheckBox::indicator { width: 18px; height: 18px; }
            QListWidget#exclList { background: #FFF; border: 1px solid #D0D0D0; border-radius: 4px; font-size: 14pt; }
            QListWidget#exclList::item { padding: 3px 6px; }
            QPushButton#smallBtn { background: #FFF; border: 1px solid #D0D0D0; border-radius: 3px; padding: 3px 10px; font-size: 14pt; }
            QPushButton#smallBtn:hover { background: #E8E8E8; border-color: #0078D4; }
            QWidget#statsBar { background: #FFF; border: 1px solid #D0D0D0; border-radius: 5px; }
            QLabel#statLabel { font-size: 14pt; color: #333; padding: 2px 6px; }
            QPushButton#simulateBtn { background: #FFF; border: 1px solid #D0D0D0; border-radius: 5px; padding: 8px 20px; font-size: 14pt; font-weight: 600; }
            QPushButton#simulateBtn:hover { background: #E8E8E8; border-color: #0078D4; }
            QPushButton#executeBtn { background: #0078D4; color: #FFF; border: none; border-radius: 5px; padding: 8px 20px; font-size: 14pt; font-weight: 700; }
            QPushButton#executeBtn:hover { background: #106EBE; }
            QPushButton#executeBtn:disabled { background: #B0B0B0; color: #DDD; }
            QPushButton#scheduleBtn { background: #FFF; border: 1px solid #D0D0D0; border-radius: 5px; padding: 8px 14px; font-size: 14pt; }
            QPushButton#scheduleBtn:hover { background: #E8E8E8; border-color: #0078D4; }
            QProgressBar { border: 1px solid #D0D0D0; border-radius: 4px; text-align: center; background: #FFF; height: 22px; font-size: 14pt; font-weight: 600; }
            QProgressBar::chunk { background: #0078D4; border-radius: 3px; }
            QLabel#logTitle { font-weight: 700; font-size: 14pt; color: #111; }
            QTextEdit#logView { background: #1E1E1E; color: #D4D4D4; border: 1px solid #D0D0D0; border-radius: 5px; padding: 6px; font-size: 14pt; }
        """)

    # ---- Helpers ----
    def _browse(self, edit):
        path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if path:
            edit.setText(path)

    def _toggle_top(self, state):
        flags = self.windowFlags()
        if state == Qt.Checked:
            self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
        self.show()

    def _add_excl(self):
        from PyQt5.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "添加排除规则", "输入文件名或扩展名 (如 .tmp 或 node_modules):")
        if ok and text.strip():
            self.excl_list.addItem(text.strip())

    def _del_excl(self):
        for item in self.excl_list.selectedItems():
            self.excl_list.takeItem(self.excl_list.row(item))

    def _update_stats(self):
        src = self.edit_src.text().strip()
        dst = self.edit_dst.text().strip()
        if os.path.isdir(src):
            try:
                cnt = sum(1 for _ in os.scandir(src))
                sz = sum(f.stat().st_size for f in os.scandir(src) if f.is_file())
                self.lbl_src_count.setText(f"源: {cnt} 项")
                self.lbl_src_size.setText(f"源大小: {fmt_size(sz)}")
            except:
                pass
        else:
            self.lbl_src_count.setText("源: -")
            self.lbl_src_size.setText("源大小: -")
        if os.path.isdir(dst):
            try:
                cnt = sum(1 for _ in os.scandir(dst))
                sz = sum(f.stat().st_size for f in os.scandir(dst) if f.is_file())
                self.lbl_dst_count.setText(f"目标: {cnt} 项")
                self.lbl_dst_size.setText(f"目标大小: {fmt_size(sz)}")
            except:
                pass
        else:
            self.lbl_dst_count.setText("目标: -")
            self.lbl_dst_size.setText("目标大小: -")

    # ---- Sync ----
    def start_sync(self, simulate=False):
        src = self.edit_src.text().strip()
        dst = self.edit_dst.text().strip()

        if not src or not os.path.isdir(src):
            QMessageBox.warning(self, "提示", "请选择有效的源文件夹")
            return
        if not dst:
            reply = QMessageBox.question(self, "创建目标",
                f"目标文件夹不存在:\n{dst}\n是否创建？",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    os.makedirs(dst, exist_ok=True)
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"创建失败: {e}")
                    return
            else:
                return
        elif not os.path.isdir(dst):
            reply = QMessageBox.question(self, "创建目标",
                f"路径不是文件夹:\n{dst}\n是否创建？",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    os.makedirs(dst, exist_ok=True)
                except:
                    return
            else:
                return

        mode = "mirror" if self.radio_mirror.isChecked() else "incremental"
        use_md5 = self.chk_md5.isChecked()

        exclude_dirs = []
        exclude_exts = []
        for i in range(self.excl_list.count()):
            text = self.excl_list.item(i).text().strip()
            if text.startswith("."):
                exclude_exts.append(text)
            else:
                exclude_dirs.append(text)

        self.log_view.clear()
        self.btn_simulate.setEnabled(False)
        self.btn_execute.setEnabled(False)
        self.pbar.setVisible(True)
        if simulate:
            self.pbar.setRange(0, 0)
            self.pbar.setFormat("正在分析...")
        else:
            self.pbar.setValue(0)
            self.pbar.setFormat("")

        if self.worker and self.worker.isRunning():
            self.worker.terminate()

        self.worker = SyncWorker(src, dst, mode, use_md5, exclude_dirs, exclude_exts, simulate)
        self.worker.log.connect(self._append_log)
        self.worker.progress.connect(self._update_progress)
        self.worker.finished.connect(lambda c, d, b: self._on_sync_done(c, d, b, simulate))
        self.worker.start()

    def _append_log(self, text):
        self.log_view.append(text)
        self.log_view.moveCursor(QTextCursor.End)

    def _update_progress(self, current, total):
        self.pbar.setMaximum(total)
        self.pbar.setValue(current)
        self.pbar.setFormat(f"{current}/{total}")

    def _on_sync_done(self, copied, deleted, total_bytes, was_simulate):
        self.pbar.setVisible(False)
        self.btn_simulate.setEnabled(True)
        self.btn_execute.setEnabled(not was_simulate)
        if was_simulate:
            self._append_log(f"[{now_str()}] 模拟完成。可点击「执行同步」开始实际操作。")

    # ---- Schedule ----
    def gen_schedule(self):
        src = self.edit_src.text().strip()
        dst = self.edit_dst.text().strip()
        if not src or not dst:
            QMessageBox.warning(self, "提示", "请先选择源文件夹和目标文件夹")
            return
        mode = "mirror" if self.radio_mirror.isChecked() else "incremental"
        use_md5 = self.chk_md5.isChecked()

        py_parts = []
        py_parts.append("import sys, os")
        py_parts.append("sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))")
        py_parts.append("from main import SyncEngine, scan_dir, should_exclude, now_str")
        py_parts.append('src = r"' + src.replace('"', '\"') + '"')
        py_parts.append('dst = r"' + dst.replace('"', '\"') + '"')
        py_parts.append('mode = "' + mode + '"')
        py_parts.append('use_md5 = ' + ('True' if use_md5 else 'False'))
        py_parts.append("exclude_dirs = []")
        py_parts.append("exclude_exts = []")
        py_parts.append("items_src = scan_dir(src, exclude_dirs, exclude_exts)")
        py_parts.append("items_dst = scan_dir(dst, exclude_dirs, exclude_exts) if os.path.exists(dst) else {}")
        py_parts.append("ops = SyncEngine.compare(items_src, items_dst, mode, use_md5)")
        py_parts.append("for o in ops:")
        py_parts.append("    SyncEngine.execute_op(o, dst, print)")
        py_parts.append('    if o["type"] in ("copy", "update"):')
        py_parts.append('        print("  " + o["type"] + ": " + o["key"])')
        py_parts.append('    elif o["type"] == "delete":')
        py_parts.append('        print("  delete: " + o["key"])')
        py_parts.append('print("[" + now_str() + "] \u540c\u6b65\u5b8c\u6210")')
        py_script = "; ".join(py_parts)

        lines = []
        lines.append("@echo off")
        lines.append("chcp 65001 >nul")
        lines.append("echo ========================================")
        lines.append("echo  文件夹同步 - 计划任务")
        lines.append("echo  源: " + src)
        lines.append("echo  目标: " + dst)
        lines.append("echo  模式: " + mode)
        lines.append("echo ========================================")
        lines.append("echo.")
        lines.append("")
        lines.append(":: 检查源是否存在")
        lines.append('if not exist "' + src + '" (')
        lines.append("    echo 源文件夹不存在: " + src)
        lines.append("    pause")
        lines.append("    exit /b 1")
        lines.append(")")
        lines.append("")
        lines.append(":: 检查目标，不存在则创建")
        lines.append('if not exist "' + dst + '" (')
        lines.append('    mkdir "' + dst + '"')
        lines.append(")")
        lines.append("")
        lines.append(":: 执行同步（使用 Python 脚本）")
        lines.append('python -c "' + py_script + '"')
        lines.append("echo.")
        lines.append("pause")


        bat_content = chr(13)+chr(10) + chr(13)+chr(10).join(lines)

        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存计划任务脚本",
            "sync_schedule.bat", "批处理文件 (*.bat)")
        if save_path:
            try:
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(bat_content)
                QMessageBox.information(self, "成功",
                    "计划任务脚本已生成:\n" + save_path + "\n\n"
                    "使用方法:\n"
                    "1. 打开 任务计划程序\n"
                    "2. 创建基本任务\n"
                    "3. 选择此 .bat 文件作为操作\n"
                    "4. 设置触发时间")
            except Exception as e:
                QMessageBox.critical(self, "错误", "写入失败: " + str(e))


def main():
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()

