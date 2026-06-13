# -*- coding: utf-8 -*-
"""闪电搜 LightningSearch - 免费版"""
import sys, os, subprocess, time, json, re
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QCheckBox, QComboBox,
    QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QProgressBar, QGroupBox,
    QTextEdit, QMenu, QSplitter, QFrame)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QIcon, QColor, QBrush, QTextCursor


class SearchWorker(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)
    _abort = False

    def __init__(self, query, filetypes, max_results=100):
        super().__init__()
        self.query = query
        self.filetypes = filetypes
        self.max_results = max_results

    def run(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from collections import deque
        try:
            q = self.query.strip()
            if not q:
                self.finished.emit([])
                return
            if q.startswith("*") and q.endswith("*"):
                q = q[1:-1]
            q = q.lower()
            results = []

            ext_map = {
                "文档": {"doc","docx","xls","xlsx","ppt","pptx","pdf","txt","md","csv"},
                "图片": {"jpg","jpeg","png","gif","bmp","webp","svg","ico"},
                "视频": {"mp4","avi","mkv","mov","wmv","flv"},
                "音频": {"mp3","wav","flac","aac","ogg","wma"},
            }
            filter_exts = set()
            for ft in self.filetypes:
                if ft in ext_map:
                    filter_exts.update(ext_map[ft])

            user = os.path.expanduser("~")
            dirs = []
            for sub in ["Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"]:
                d = os.path.join(user, sub)
                if os.path.isdir(d):
                    dirs.append(d)

            for d_letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
                root = d_letter + ":\\"
                if os.path.exists(root):
                    user_on_drive = os.path.join(root, "Users")
                    if os.path.isdir(user_on_drive):
                        try:
                            for uname in os.listdir(user_on_drive):
                                for sub in ["Desktop", "Documents", "Downloads", "Pictures"]:
                                    up = os.path.join(user_on_drive, uname, sub)
                                    if os.path.isdir(up):
                                        dirs.append(up)
                        except:
                            pass

            dirs = list(dict.fromkeys(dirs))
            skip_prefixes = ["$Recycle.Bin", "System Volume Information", "Windows", "Program Files",
                           "Program Files (x86)", "ProgramData", "Recovery", "Config.Msi",
                           "MSOCache", "PerfLogs", "boot", "tmp", "temp", "cache", "AppData",
                           "node_modules", ".git", ".svn", "__pycache__", "vendor", ".cache"]

            def should_skip(name):
                nl = name.lower()
                for s in skip_prefixes:
                    if s.lower() in nl:
                        return True
                return False

            def search_dir(d):
                local_res = []
                try:
                    scan_queue = deque()
                    scan_queue.append((d, 0))
                    max_depth = 8
                    while scan_queue:
                        if self._abort:
                            break
                        current, depth = scan_queue.popleft()
                        if depth > max_depth:
                            continue
                        try:
                            with os.scandir(current) as it:
                                for entry in it:
                                    if self._abort:
                                        return local_res
                                    if should_skip(entry.name):
                                        continue
                                    try:
                                        if entry.is_dir():
                                            if depth < max_depth:
                                                scan_queue.append((entry.path, depth + 1))
                                        elif entry.is_file():
                                            fname = entry.name
                                            if q in fname.lower():
                                                if filter_exts:
                                                    ext = os.path.splitext(fname)[1].lower().lstrip(".")
                                                    if ext not in filter_exts:
                                                        continue
                                                try:
                                                    st = entry.stat()
                                                    sz = str(st.st_size)
                                                    dt = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                                                except:
                                                    sz = ""
                                                    dt = ""
                                                local_res.append({"name": fname, "path": entry.path, "size": sz, "date": dt})
                                                if self.max_results > 0 and len(local_res) >= self.max_results:
                                                    return local_res
                                    except (PermissionError, OSError):
                                        continue
                        except (PermissionError, OSError):
                            continue
                except:
                    pass
                return local_res

            with ThreadPoolExecutor(max_workers=min(8, len(dirs))) as pool:
                futures = {pool.submit(search_dir, d): i for i, d in enumerate(dirs)}
                for i, f in enumerate(as_completed(futures)):
                    if self._abort:
                        break
                    self.progress.emit(int((i + 1) / len(dirs) * 100))
                    results.extend(f.result())
                    if self.max_results > 0 and len(results) >= self.max_results:
                        self._abort = True
                        break

            all_res = results[:self.max_results] if self.max_results > 0 else results
            self.finished.emit(all_res)
        except Exception as e:
            self.error.emit("搜索出错: " + str(e))

class FreeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.results = []
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._do_search)
        self.worker = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("闪电搜 · 免费版")
        self.resize(1000, 700)
        self.setMinimumSize(800, 500)
        font = QFont("Segoe UI", 14)
        self.setFont(font)
        cw = QWidget(); self.setCentralWidget(cw)
        ml = QVBoxLayout(cw); ml.setSpacing(8); ml.setContentsMargins(12,12,12,12)

        tb = QHBoxLayout(); tb.setSpacing(8)
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("输入关键词搜索... (自动模糊搜索)")
        self.edit_search.setMinimumHeight(38)
        self.edit_search.textChanged.connect(self._on_text_changed)
        self.edit_search.returnPressed.connect(self._do_search)
        tb.addWidget(self.edit_search, 1)
        self.combo_type = QComboBox()
        self.combo_type.addItems(["全部", "文档", "图片", "视频", "音频"])
        self.combo_type.setMinimumHeight(38)
        tb.addWidget(self.combo_type)
        self.btn_search = QPushButton("搜索")
        self.btn_search.setMinimumHeight(38)
        self.btn_search.clicked.connect(self._do_search)
        self.btn_search.setStyleSheet("background:#0078D4;color:#FFF;border:none;padding:8px 20px;border-radius:4px;font-size:16pt;font-weight:bold;")
        tb.addWidget(self.btn_search)
        self.chk_top = QCheckBox("总在最前")
        self.chk_top.setChecked(True)
        self.chk_top.stateChanged.connect(self._top)
        self.chk_top.setStyleSheet("font-size:14pt;color:#000;")
        tb.addWidget(self.chk_top)
        ml.addLayout(tb)

        self.lbl_status = QLabel("请输入关键词搜索")
        self.lbl_status.setStyleSheet("font-size:14pt;color:#333;")
        ml.addWidget(self.lbl_status)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["文件名", "路径", "修改时间", "大小"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._open_file)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.setStyleSheet("QTableWidget{background:#FFF;color:#000;border:2px solid #CCC;border-radius:4px;font-size:14pt;}QTableWidget::item{padding:4px 8px;}QTableWidget::item:alternate{background:#F5F5F5;}QHeaderView::section{font-size:13pt;font-weight:bold;color:#000;background:#F0F0F0;border:1px solid #DDD;padding:6px 8px;}")
        ml.addWidget(self.table, 1)

        self.pb = QProgressBar()
        self.pb.setVisible(False)
        self.pb.setStyleSheet("font-size:12pt;color:#FFF;text-align:center;border:1px solid #CCC;border-radius:4px;background:#F0F0F0;QProgressBar::chunk{background:#0078D4;border-radius:3px;}")
        ml.addWidget(self.pb)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(100)
        self.log.setStyleSheet("font-size:12pt;color:#333;background:#F9F9F9;border:2px solid #CCC;border-radius:4px;padding:4px;")
        ml.addWidget(self.log)
        self._log("欢迎使用闪电搜 · 免费版")

        self.setStyleSheet("QMainWindow{background:#FFF;}QWidget{background:#FFF;color:#000;}QLineEdit{border:2px solid #CCC;border-radius:4px;padding:6px 10px;font-size:14pt;color:#000;background:#FFF;}QLineEdit:focus{border:3px solid #0078D4;}QComboBox{border:2px solid #CCC;border-radius:4px;padding:6px 10px;font-size:14pt;color:#000;background:#FFF;}QComboBox:focus{border:3px solid #0078D4;}QCheckBox{font-size:14pt;color:#000;spacing:6px;}QGroupBox{font-size:16pt;font-weight:bold;color:#000;border:2px solid #DDD;border-radius:6px;margin-top:12px;padding:12px 8px 8px;}QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 6px;}QProgressBar{font-size:12pt;color:#FFF;text-align:center;border:1px solid #CCC;border-radius:4px;background:#F0F0F0;}QProgressBar::chunk{background:#0078D4;border-radius:3px;}")

    def _top(self, s):
        f = self.windowFlags()
        self.setWindowFlags(f | Qt.WindowStaysOnTopHint if s == Qt.Checked else f & ~Qt.WindowStaysOnTopHint)
        self.show()

    def _log(self, t):
        self.log.append(t); c = self.log.textCursor(); c.movePosition(QTextCursor.End); self.log.setTextCursor(c)

    def _on_text_changed(self):
        self.search_timer.start(300)

    def _do_search(self):
        self.search_timer.stop()
        query = self.edit_search.text().strip()
        if not query:
            QMessageBox.warning(self, "提示", "请输入搜索关键词")
            return
        ft = self.combo_type.currentText()
        filetypes = [ft] if ft != "全部" else []
        self._log("[搜索] " + query + " (" + ft + ")")
        self.btn_search.setEnabled(False)
        self.pb.setVisible(True); self.pb.setRange(0, 0)
        self.worker = SearchWorker(query, filetypes, 100)
        self.worker.finished.connect(self._on_results)
        self.worker.error.connect(self._on_err)
        self.worker.progress.connect(lambda v: self.pb.setValue(v))
        self.worker.start()

    def _on_results(self, results):
        self.results = results
        self.pb.setVisible(False)
        self.btn_search.setEnabled(True)
        self.table.setRowCount(0)
        self.lbl_status.setText("找到 " + str(len(results)) + " 条结果 (免费版最多100条)")
        if not results:
            self._log("[结果] 无匹配文件")
            return
        for r in results:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(r["name"]))
            self.table.setItem(row, 1, QTableWidgetItem(r["path"]))
            self.table.setItem(row, 2, QTableWidgetItem(r["date"]))
            sz = r.get("size", "")
            if sz:
                try:
                    sz_i = int(sz)
                    if sz_i < 1024:
                        sz_d = str(sz_i) + " B"
                    elif sz_i < 1048576:
                        sz_d = "{:.1f} KB".format(sz_i / 1024)
                    else:
                        sz_d = "{:.1f} MB".format(sz_i / 1048576)
                    self.table.setItem(row, 3, QTableWidgetItem(sz_d))
                except:
                    self.table.setItem(row, 3, QTableWidgetItem(sz))
            else:
                self.table.setItem(row, 3, QTableWidgetItem(""))
        self._log("[完成] 找到 " + str(len(results)) + " 个文件")

    def _on_err(self, msg):
        self.pb.setVisible(False); self.btn_search.setEnabled(True)
        self._log("[错误] " + msg); QMessageBox.critical(self, "错误", msg)

    def _open_file(self, idx):
        row = idx.row()
        if row < len(self.results):
            path = self.results[row]["path"]
            try:
                os.startfile(path)
            except Exception as e:
                self._log("[错误] 无法打开: " + str(e))

    def _context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return
        row = item.row()
        if row >= len(self.results):
            return
        path = self.results[row]["path"]
        menu = QMenu()
        act_copy = menu.addAction("复制路径")
        act_open = menu.addAction("打开文件")
        act_open_folder = menu.addAction("打开所在文件夹")
        action = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if action == act_copy:
            QApplication.clipboard().setText(path)
            self._log("[操作] 路径已复制: " + path)
        elif action == act_open:
            try:
                os.startfile(path)
            except Exception as e:
                self._log("[错误] " + str(e))
        elif action == act_open_folder:
            try:
                subprocess.run(["explorer", "/select,", path])
            except Exception as e:
                self._log("[错误] " + str(e))


def main():
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 14))
    w = FreeWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
