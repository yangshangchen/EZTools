# -*- coding: utf-8 -*-
"""闪电搜 LightningSearch - 免费版"""
import sys, os, subprocess, time, json, re, sqlite3, shutil
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt5.QtWidgets import (QListWidget, QListWidgetItem, QInputDialog, QCompleter,
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QCheckBox, QComboBox,
    QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QProgressBar, QGroupBox,
    QTextEdit, QMenu, QSplitter, QFrame)
from PyQt5.QtCore import (Qt, QTimer, QThread, pyqtSignal, QSize, QStringListModel)
from PyQt5.QtGui import QFont, QIcon, QColor, QBrush, QTextCursor


class SearchWorker(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)
    _abort = False

    def __init__(self, query, filetypes, max_results=0):
        super().__init__()
        self.query = query
        self.filetypes = filetypes
        self.max_results = max_results

    def _get_search_dirs(self):
        dirs = []
        user = os.path.expanduser("~")
        for sub in ["Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"]:
            d = os.path.join(user, sub)
            if os.path.isdir(d):
                dirs.append(d)
        for dl in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            root = dl + ":\\"
            if os.path.exists(root):
                dirs.append(root)
        seen = set()
        result = []
        for d in dirs:
            if d not in seen:
                seen.add(d)
                result.append(d)
        return result

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

            dirs = self._get_search_dirs()
            if not dirs:
                self.error.emit("未找到可搜索的目录")
                return

            skip_prefixes = ["$Recycle.Bin", "System Volume Information", "Windows", "Program Files",
                           "Program Files (x86)", "ProgramData", "Recovery", "Config.Msi",
                           "MSOCache", "PerfLogs", "boot", "tmp", "temp", "cache", "AppData",
                           "node_modules", ".git", ".svn", "__pycache__", "vendor", ".cache"]

            def should_skip(name):
                nl = name.lower()
                return any(s.lower() in nl for s in skip_prefixes)

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



DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lightning_tags.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, color TEXT DEFAULT '#0078D4')")
    c.execute("CREATE TABLE IF NOT EXISTS file_tags (file_path TEXT NOT NULL, tag_id INTEGER NOT NULL, FOREIGN KEY(tag_id) REFERENCES tags(id), PRIMARY KEY(file_path, tag_id))")
    c.execute("CREATE TABLE IF NOT EXISTS search_history (id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT NOT NULL, searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    return conn

class ProWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.results = []
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._do_search)
        self.worker = None
        self.db_conn = init_db()
        self.current_tags = []
        self.init_ui()
        self._load_tags()
        self._load_history()


    def _load_history(self):
        try:
            c = self.db_conn.cursor()
            c.execute("SELECT keyword FROM search_history ORDER BY searched_at DESC LIMIT 20")
            keywords = [row[0] for row in c.fetchall()]
            model = QStringListModel()
            model.setStringList(keywords)
            completer = QCompleter(model, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setMaxVisibleItems(10)
            self.edit_search.setCompleter(completer)
        except Exception as e:
            self._log("[错误] 加载搜索历史: " + str(e))

    def _save_history(self, keyword):
        try:
            c = self.db_conn.cursor()
            c.execute("DELETE FROM search_history WHERE keyword=?", (keyword,))
            c.execute("INSERT INTO search_history (keyword) VALUES (?)", (keyword,))
            c.execute("DELETE FROM search_history WHERE id NOT IN (SELECT id FROM search_history ORDER BY searched_at DESC LIMIT 20)")
            self.db_conn.commit()
        except Exception as e:
            self._log("[错误] 保存历史: " + str(e))

    def _load_tags(self):
        try:
            self.tag_list.clear()
            item_all = QListWidgetItem("全部文件")
            item_all.setData(Qt.UserRole, 0)
            self.tag_list.addItem(item_all)
            c = self.db_conn.cursor()
            for row in c.execute("SELECT id, name FROM tags ORDER BY name"):
                item = QListWidgetItem(row[1])
                item.setData(Qt.UserRole, row[0])
                self.tag_list.addItem(item)
        except Exception as e:
            self._log("[错误] 加载标签: " + str(e))

    def _add_tag_dialog(self):
        name, ok = QInputDialog.getText(self, "添加标签", "输入标签名称:")
        if not ok or not name.strip():
            return
        name = name.strip()
        try:
            c = self.db_conn.cursor()
            c.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            self.db_conn.commit()
            self._load_tags()
            self._log("[操作] 标签已添加: " + name)
        except Exception as e:
            self._log("[错误] 添加标签失败: " + str(e))

    def _update_table(self, results):
        self.table.setRowCount(0)
        for r in results:
            row = self.table.rowCount()
            self.table.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Unchecked)
            self.table.setItem(row, 0, chk)
            self.table.setItem(row, 1, QTableWidgetItem(r["name"]))
            self.table.setItem(row, 2, QTableWidgetItem(r["path"]))
            self.table.setItem(row, 3, QTableWidgetItem(r.get("date", "")))
            sz = r.get("size", "")
            if sz:
                try:
                    si = int(sz)
                    sd = str(si) + " B"
                    if si >= 1024:
                        sd = "{:.1f} KB".format(si / 1024)
                    if si >= 1048576:
                        sd = "{:.1f} MB".format(si / 1048576)
                    self.table.setItem(row, 4, QTableWidgetItem(sd))
                except:
                    self.table.setItem(row, 4, QTableWidgetItem(sz))
            else:
                self.table.setItem(row, 4, QTableWidgetItem(""))
            QApplication.processEvents()

    def _filter_by_tag(self, item):
        tag_id = item.data(Qt.UserRole)
        if tag_id == 0:
            self._update_table(self.results)
            self.lbl_status.setText("全部文件 (" + str(len(self.results)) + " 条)")
            return
        c = self.db_conn.cursor()
        c.execute("SELECT file_path FROM file_tags WHERE tag_id=?", (tag_id,))
        tagged = set(r[0] for r in c.fetchall())
        filtered = [r for r in self.results if r["path"] in tagged]
        self._update_table(filtered)
        self.lbl_status.setText("标签: " + item.text() + " (" + str(len(filtered)) + " 条)")

    def _tag_file_dialog(self, fp):
        try:
            c = self.db_conn.cursor()
            tags = c.execute("SELECT id, name FROM tags ORDER BY name").fetchall()
            if not tags:
                QMessageBox.warning(self, "提示", "先添加标签")
                return
            names = [t[1] for t in tags]
            tag, ok = QInputDialog.getItem(self, "添加标签", "文件: " + os.path.basename(fp), names, 0, False)
            if ok and tag:
                tid = next(t[0] for t in tags if t[1] == tag)
                c.execute("INSERT OR IGNORE INTO file_tags (file_path, tag_id) VALUES (?,?)", (fp, tid))
                self.db_conn.commit()
                self._log("[操作] 标签已添加: " + os.path.basename(fp) + " -> " + tag)
        except Exception as e:
            self._log("[错误] 标签失败: " + str(e))

    def init_ui(self):
        self.setWindowTitle("闪电搜 · 专业版")
        self.resize(1000, 700)
        self.setMinimumSize(800, 500)
        font = QFont("Segoe UI", 14)
        self.setFont(font)
        cw = QWidget(); self.setCentralWidget(cw)
        ml = QVBoxLayout(cw); ml.setSpacing(8); ml.setContentsMargins(12,12,12,12)

        tb = QHBoxLayout(); tb.setSpacing(8)
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("输入关键词搜索... (专业版智能补全)")
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

        # Main splitter
        main_splitter = QSplitter(Qt.Horizontal)

        # Left: tag panel
        left_w = QWidget()
        left_l = QVBoxLayout(left_w); left_l.setContentsMargins(0,0,4,0)
        tag_title = QLabel("标签筛选")
        tag_title.setStyleSheet("font-size:16pt;font-weight:bold;color:#000;")
        left_l.addWidget(tag_title)
        self.tag_list = QListWidget()
        self.tag_list.itemClicked.connect(self._filter_by_tag)
        self.tag_list.setMinimumWidth(140)
        self.tag_list.setStyleSheet("font-size:14pt;border:2px solid #CCC;border-radius:4px;padding:4px;background:#FFF;color:#000;")
        left_l.addWidget(self.tag_list, 1)
        btn_add_tag = QPushButton("+ 添加标签")
        btn_add_tag.clicked.connect(self._add_tag_dialog)
        btn_add_tag.setStyleSheet("background:#0078D4;color:#FFF;border:none;border-radius:4px;font-size:14pt;font-weight:bold;padding:6px;")
        left_l.addWidget(btn_add_tag)
        main_splitter.addWidget(left_w)

        # Center
        center_w = QWidget()
        center_l = QVBoxLayout(center_w); center_l.setContentsMargins(4,0,4,0)
        self.lbl_status = QLabel("请输入关键词搜索")
        self.lbl_status.setStyleSheet("font-size:14pt;color:#333;")
        center_l.addWidget(self.lbl_status)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["选中", "文件名", "路径", "修改时间", "大小"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._open_file)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.setStyleSheet("QTableWidget{background:#FFF;color:#000;border:2px solid #CCC;border-radius:4px;font-size:14pt;}QTableWidget::item{padding:4px 8px;}QTableWidget::item:alternate{background:#F5F5F5;}QHeaderView::section{font-size:13pt;font-weight:bold;color:#000;background:#F0F0F0;border:1px solid #DDD;padding:6px 8px;}")
        center_l.addWidget(self.table, 1)
        self.pb = QProgressBar()
        self.pb.setVisible(False)
        self.pb.setStyleSheet("font-size:12pt;color:#FFF;text-align:center;border:1px solid #CCC;border-radius:4px;background:#F0F0F0;QProgressBar::chunk{background:#0078D4;border-radius:3px;}")
        center_l.addWidget(self.pb)
        main_splitter.addWidget(center_w)

        # Right
        right_w = QWidget()
        right_l = QVBoxLayout(right_w); right_l.setContentsMargins(4,0,0,0)
        act_title = QLabel("批量操作")
        act_title.setStyleSheet("font-size:16pt;font-weight:bold;color:#000;")
        right_l.addWidget(act_title)
        btn_cp = QPushButton("批量复制到...")
        btn_cp.clicked.connect(self._batch_copy)
        btn_cp.setStyleSheet("background:#0078D4;color:#FFF;border:none;border-radius:4px;font-size:14pt;padding:6px;")
        right_l.addWidget(btn_cp)
        btn_rn = QPushButton("批量重命名...")
        btn_rn.clicked.connect(self._batch_rename)
        btn_rn.setStyleSheet("background:#0078D4;color:#FFF;border:none;border-radius:4px;font-size:14pt;padding:6px;")
        right_l.addWidget(btn_rn)
        btn_dl = QPushButton("批量删除...")
        btn_dl.clicked.connect(self._batch_delete)
        btn_dl.setStyleSheet("background:#D40000;color:#FFF;border:none;border-radius:4px;font-size:14pt;padding:6px;")
        right_l.addWidget(btn_dl)
        right_l.addSpacing(16)
        ex_title = QLabel("导出结果")
        ex_title.setStyleSheet("font-size:16pt;font-weight:bold;color:#000;")
        right_l.addWidget(ex_title)
        btn_csv = QPushButton("导出 CSV")
        btn_csv.clicked.connect(lambda: self._export("csv"))
        btn_csv.setStyleSheet("background:#0078D4;color:#FFF;border:none;border-radius:4px;font-size:14pt;padding:6px;")
        right_l.addWidget(btn_csv)
        btn_xl = QPushButton("导出 Excel")
        btn_xl.clicked.connect(lambda: self._export("xlsx"))
        btn_xl.setStyleSheet("background:#0078D4;color:#FFF;border:none;border-radius:4px;font-size:14pt;padding:6px;")
        right_l.addWidget(btn_xl)
        right_l.addStretch()
        main_splitter.addWidget(right_w)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)
        main_splitter.setStretchFactor(2, 1)
        ml.addWidget(main_splitter, 1)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(100)
        self.log.setStyleSheet("font-size:12pt;color:#333;background:#F9F9F9;border:2px solid #CCC;border-radius:4px;padding:4px;")
        ml.addWidget(self.log)
        self._log("欢迎使用闪电搜 · 专业版")

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
            return
        self._save_history(query)
        self._load_history()
        ft = self.combo_type.currentText()
        filetypes = [ft] if ft != "全部" else []
        query = "*" + query + "*"
        self._log("[搜索] " + query + " (" + ft + ")")
        self.btn_search.setEnabled(False)
        self.pb.setVisible(True); self.pb.setRange(0, 0)
        self.worker = SearchWorker(query, filetypes, 0)
        self.worker.finished.connect(self._on_results)
        self.worker.error.connect(self._on_err)
        self.worker.progress.connect(lambda v: self.pb.setValue(v))
        self.worker.start()

    def _on_results(self, results):
        self.results = results
        self.pb.setVisible(False)
        self.btn_search.setEnabled(True)
        self.table.setRowCount(0)
        self.lbl_status.setText("找到 " + str(len(results)) + " 条结果 (专业版无限)")
        if not results:
            self._log("[结果] 无匹配文件")
            return
        for r in results:
            row = self.table.rowCount()
            self.table.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Unchecked)
            self.table.setItem(row, 0, chk)
            self.table.setItem(row, 1, QTableWidgetItem(r["name"]))
            self.table.setItem(row, 2, QTableWidgetItem(r["path"]))
            self.table.setItem(row, 3, QTableWidgetItem(r["date"]))
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
                    self.table.setItem(row, 4, QTableWidgetItem(sz_d))
                except:
                    self.table.setItem(row, 4, QTableWidgetItem(sz))
            else:
                self.table.setItem(row, 4, QTableWidgetItem(""))
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
        act_tag = menu.addAction("添加标签...")
        action = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if action == act_copy:
            QApplication.clipboard().setText(path)
            self._log("[操作] 路径已复制: " + path)
        elif action == act_tag:
            self._tag_file_dialog(path)
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


    def _get_selected_paths(self):
        paths = []
        for row in range(self.table.rowCount()):
            it = self.table.item(row, 0)
            if it and it.checkState() == Qt.Checked:
                paths.append(self.table.item(row, 2).text())
        return paths

    def _batch_copy(self):
        paths = self._get_selected_paths()
        if not paths:
            QMessageBox.warning(self, "提示", "请先勾选文件")
            return
        dst = QFileDialog.getExistingDirectory(self, "目标文件夹")
        if not dst:
            return
        ok = 0
        for s in paths:
            try:
                if os.path.isfile(s):
                    shutil.copy2(s, dst)
                    ok += 1
            except Exception as e:
                self._log("[错误] 复制失败: " + str(e))
        QMessageBox.information(self, "完成", "复制 " + str(ok) + "/" + str(len(paths)))
        self._log("[操作] 批量复制: " + str(ok) + "/" + str(len(paths)))

    def _batch_rename(self):
        paths = self._get_selected_paths()
        if not paths:
            QMessageBox.warning(self, "提示", "请先勾选文件")
            return
        pat, ok = QInputDialog.getText(self, "批量重命名", "命名模板 (支持 {n}):", text="文件_{n}")
        if not ok or not pat.strip():
            return
        ok = 0
        for i, s in enumerate(paths):
            try:
                d = os.path.dirname(s)
                ext = os.path.splitext(s)[1]
                n = pat.replace("{n}", str(i+1).zfill(3)) + ext
                dst = os.path.join(d, n)
                if os.path.exists(dst) and dst != s:
                    self._log("[跳过] 已存在: " + dst)
                    continue
                os.rename(s, dst)
                ok += 1
            except Exception as e:
                self._log("[错误] 重命名失败: " + str(e))
        QMessageBox.information(self, "完成", "重命名 " + str(ok) + "/" + str(len(paths)))
        self._log("[操作] 批量重命名: " + str(ok) + "/" + str(len(paths)))
        self._do_search()

    def _batch_delete(self):
        paths = self._get_selected_paths()
        if not paths:
            QMessageBox.warning(self, "提示", "请先勾选文件")
            return
        r = QMessageBox.warning(self, "确认删除", "删除 " + str(len(paths)) + " 个文件?", QMessageBox.Yes|QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        ok = 0
        for s in paths:
            try:
                if os.path.isfile(s):
                    os.remove(s)
                    ok += 1
            except Exception as e:
                self._log("[错误] 删除失败: " + str(e))
        QMessageBox.information(self, "完成", "删除 " + str(ok) + "/" + str(len(paths)))
        self._log("[操作] 批量删除: " + str(ok) + "/" + str(len(paths)))
        self._do_search()

    def _export(self, fmt):
        if not self.results:
            QMessageBox.warning(self, "提示", "无搜索结果可导出")
            return
        if fmt == "csv":
            path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", "results.csv", "CSV (*.csv)")
            if not path:
                return
            try:
                import csv
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f)
                    w.writerow(["文件名","路径","修改时间","大小"])
                    for r in self.results:
                        w.writerow([r["name"],r["path"],r.get("date",""),r.get("size","")])
                QMessageBox.information(self, "完成", "导出 " + str(len(self.results)) + " 条\n" + path)
            except Exception as e:
                QMessageBox.critical(self, "错误", "导出失败: " + str(e))
        else:
            path, _ = QFileDialog.getSaveFileName(self, "导出 Excel", "results.xlsx", "Excel (*.xlsx)")
            if not path:
                return
            try:
                import pandas as pd
                df = pd.DataFrame(self.results)
                df.to_excel(path, index=False, engine="openpyxl")
                QMessageBox.information(self, "完成", "导出 " + str(len(self.results)) + " 条\n" + path)
            except ImportError:
                QMessageBox.critical(self, "错误", "缺少 pandas/openpyxl\npip install pandas openpyxl")
            except Exception as e:
                QMessageBox.critical(self, "错误", "导出失败: " + str(e))


def main():
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 14))
    w = ProWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
