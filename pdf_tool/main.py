#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PDF 页面操作工具 — 合并 / 拆分 / 提取
依赖: PyMuPDF (pip install PyMuPDF)
"""

import sys, os, re, subprocess
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QListWidget, QAbstractItemView,
    QFileDialog, QMessageBox, QProgressBar, QLineEdit, QFrame,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QFontDatabase

# ── 检查 PyMuPDF ──────────────────────────────────────────────────────

try:
    import fitz
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False


# ── 后台工作线程 ──────────────────────────────────────────────────────

class PdfWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    _abort = False

    def __init__(self, op, params):
        super().__init__()
        self.op = op
        self.params = params

    def run(self):
        self._abort = False
        if not PYMUPDF_OK:
            self.finished.emit(False, "未安装 PyMuPDF，请运行: pip install PyMuPDF")
            return
        try:
            {
                "merge":   self._merge,
                "split":   self._split,
                "extract": self._extract,
            }[self.op]()
        except Exception as e:
            self.finished.emit(False, f"\u9519\u8bef: {str(e)}")

    def cancel(self):
        self._abort = True

    # ── 合并 ────────────────────────────────────────────────────

    def _merge(self):
        files, out = self.params["files"], self.params["output"]
        self.progress.emit(0, f"\u51c6\u5907\u5408\u5e76 {len(files)} \u4e2a\u6587\u4ef6\u2026")
        merger = fitz.open()
        for i, fp in enumerate(files):
            if self._abort:
                merger.close(); self.finished.emit(False, "\u64cd\u4f5c\u5df2\u53d6\u6d88"); return
            self.progress.emit(int((i+1)/len(files)*90),
                               f"\u6b63\u5728\u8bfb\u53d6: {os.path.basename(fp)}")
            try:
                doc = fitz.open(fp)
            except Exception:
                merger.close(); self.finished.emit(False, f"\u65e0\u6cd5\u6253\u5f00\u6587\u4ef6(\u53ef\u80fd\u635f\u574f\u6216\u52a0\u5bc6):\n{fp}"); return
            merger.insert_pdf(doc)
            doc.close()
        if self._abort:
            merger.close(); self.finished.emit(False, "\u64cd\u4f5c\u5df2\u53d6\u6d88"); return
        self.progress.emit(95, "\u6b63\u5728\u4fdd\u5b58\u2026")
        merger.save(out, garbage=4, deflate=True)
        merger.close()
        self.finished.emit(True, f"\u5408\u5e76\u5b8c\u6210\uff0c\u5171 {len(files)} \u4e2a\u6587\u4ef6\n\u8f93\u51fa: {out}")

    # ── 拆分 ────────────────────────────────────────────────────

    def _split(self):
        files, out_dir = self.params["files"], self.params["output_dir"]
        total = 0
        doc_list = []
        for fp in files:
            if self._abort:
                self.finished.emit(False, "\u64cd\u4f5c\u5df2\u53d6\u6d88"); return
            try:
                d = fitz.open(fp)
            except Exception:
                self.finished.emit(False, f"\u65e0\u6cd5\u6253\u5f00\u6587\u4ef6:\n{fp}"); return
            doc_list.append((fp, d))
            total += d.page_count
        done = 0
        for fp, doc in doc_list:
            base = os.path.splitext(os.path.basename(fp))[0]
            for pg in range(doc.page_count):
                if self._abort:
                    self._close_all(doc_list); self.finished.emit(False, "\u64cd\u4f5c\u5df2\u53d6\u6d88"); return
                self.progress.emit(int((done+1)/total*95), f"\u62c6\u5206\u7b2c {done+1}/{total} \u9875")
                src = fitz.open()
                src.insert_pdf(doc, from_page=pg, to_page=pg)
                src.save(os.path.join(out_dir, f"{base}_{pg+1}.pdf"), garbage=4)
                src.close()
                done += 1
        self._close_all(doc_list)
        self.finished.emit(True, f"\u62c6\u5206\u5b8c\u6210\uff0c\u5171 {done} \u9875\n\u8f93\u51fa\u6587\u4ef6\u5939: {out_dir}")

    def _close_all(self, lst):
        for _, d in lst:
            try: d.close()
            except: pass

    # ── 提取 ────────────────────────────────────────────────────

    def _extract(self):
        files, out, ranges = self.params["files"], self.params["output"], self.params["ranges"]
        total = sum(e-s+1 for s,e in ranges)
        dst = fitz.open()
        for fp in files:
            if self._abort:
                dst.close(); self.finished.emit(False, "\u64cd\u4f5c\u5df2\u53d6\u6d88"); return
            try:
                src = fitz.open(fp)
            except Exception:
                dst.close(); self.finished.emit(False, f"\u65e0\u6cd5\u6253\u5f00\u6587\u4ef6:\n{fp}"); return
            done = 0
            for s, e in ranges:
                for pg in range(s, min(e, src.page_count-1)+1):
                    if self._abort:
                        src.close(); dst.close(); self.finished.emit(False, "\u64cd\u4f5c\u5df2\u53d6\u6d88"); return
                    self.progress.emit(int((done+1)/total*95), f"\u63d0\u53d6\u7b2c {pg+1} \u9875")
                    dst.insert_pdf(src, from_page=pg, to_page=pg)
                    done += 1
            src.close()
        if self._abort:
            dst.close(); self.finished.emit(False, "\u64cd\u4f5c\u5df2\u53d6\u6d88"); return
        dst.save(out, garbage=4, deflate=True)
        dst.close()
        self.finished.emit(True, f"\u63d0\u53d6\u5b8c\u6210\uff0c\u5171 {total} \u9875\n\u8f93\u51fa: {out}")


# ── 带拖拽的 QListWidget ─────────────────────────────────────────────

class DropList(QListWidget):
    dropSignal = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = []
            for url in e.mimeData().urls():
                fp = url.toLocalFile()
                if fp.lower().endswith(".pdf"):
                    paths.append(fp)
            if paths:
                self.dropSignal.emit(paths)
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


# ── 样式 ──────────────────────────────────────────────────────────────

STYLE = """
QMainWindow { background: #1a1a2a; }
QWidget#centralWidget { background: transparent; }
QTabWidget::pane { background: #25253a; border: 1px solid #3a3a55; border-radius: 8px; }
QTabWidget::tab-bar { alignment: center; }
QTabBar::tab {
    background: #2a2a40; color: #8888aa; border: none;
    padding: 10px 24px; margin: 2px; font-size: 14px; font-weight: 600;
    border-radius: 6px;
}
QTabBar::tab:selected { background: #3a6a9a; color: #ffffff; }
QTabBar::tab:hover:!selected { background: #3a3a55; color: #ccccdd; }
QLabel { color: #e8e8f0; font-size: 14px; background: transparent; }
QListWidget {
    background: #1e1e32; border: 1px solid #3a3a55; border-radius: 6px;
    color: #ffffff; font-size: 13px; padding: 4px;
}
QListWidget::item { padding: 6px 8px; border-radius: 4px; }
QListWidget::item:selected { background: #3a6a9a; }
QLineEdit {
    background: #1e1e32; border: 1px solid #3a3a55; border-radius: 6px;
    color: #ffffff; padding: 7px 10px; font-size: 14px;
}
QLineEdit:focus { border-color: #5a8fc0; }
QPushButton {
    background: #3a3a55; border: 1px solid #4a4a68; border-radius: 8px;
    color: #ffffff; padding: 9px 18px; font-size: 14px; min-height: 22px;
}
QPushButton:hover { background: #4a4a68; border-color: #5a8fc0; }
QPushButton:pressed { background: #2a2a45; }
QPushButton#btnPrimary { background: #2a5a8a; border-color: #3a7aba; font-weight: 600; }
QPushButton#btnPrimary:hover { background: #3a6a9a; }
QPushButton#btnDanger { background: #5a3030; border-color: #7a4040; }
QPushButton#btnDanger:hover { background: #6a4040; }
QProgressBar {
    border: 1px solid #3a3a55; border-radius: 6px;
    background: #1e1e32; text-align: center; color: #ffffff;
    font-size: 13px; height: 22px;
}
QProgressBar::chunk { background: #3a7aba; border-radius: 5px; }
QFrame#panel { background: #25253a; border: 1px solid #3a3a55; border-radius: 10px; }
"""


# ── 主窗口 ────────────────────────────────────────────────────────────

class PdfTool(QMainWindow):
    def __init__(self):
        super().__init__()
        if not PYMUPDF_OK:
            QMessageBox.critical(self, "\u7f3a\u5c11\u4f9d\u8d56",
                "\u672a\u5b89\u88c5 PyMuPDF (fitz)\u3002\n\n\u8bf7\u8fd0\u884c: pip install PyMuPDF\n\n\u5b89\u88c5\u540e\u91cd\u542f\u7a0b\u5e8f\u3002")
        self.worker = None
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("PDF \u9875\u9762\u64cd\u4f5c\u5de5\u5177")
        self.setObjectName("mainWindow")
        self.resize(800, 600)
        self.setMinimumSize(700, 520)

        cw = QWidget(); cw.setObjectName("centralWidget")
        self.setCentralWidget(cw)
        ml = QVBoxLayout(cw); ml.setContentsMargins(14,10,14,10); ml.setSpacing(8)

        # Title
        tl = QLabel("PDF \u9875\u9762\u64cd\u4f5c\u5de5\u5177  \u2014  \u5408\u5e76 / \u62c6\u5206 / \u63d0\u53d6")
        tl.setStyleSheet("font-size:18px;font-weight:bold;color:#ffffff;padding:4px 0;")
        ml.addWidget(tl)

        # Progress
        self.pbar = QProgressBar(); self.pbar.setVisible(False)
        ml.addWidget(self.pbar)
        self.pstatus = QLabel(""); self.pstatus.setStyleSheet("color:#8888aa;")
        ml.addWidget(self.pstatus)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_merge(), "  \u5408\u5e76  ")
        self.tabs.addTab(self._tab_split(), "  \u62c6\u5206  ")
        self.tabs.addTab(self._tab_extract(), "  \u63d0\u53d6  ")
        ml.addWidget(self.tabs)
        self.setStyleSheet(STYLE)

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            r = QMessageBox.question(self, "\u786e\u8ba4", "\u6b63\u5728\u5904\u7406\u4e2d\uff0c\u786e\u5b9a\u8981\u9000\u51fa\u5417\uff1f",
                                     QMessageBox.Yes|QMessageBox.No)
            if r == QMessageBox.Yes:
                self.worker.cancel(); self.worker.quit(); self.worker.wait(3000)
                e.accept()
            else: e.ignore()
        else: e.accept()

    # ── 通用组件 ────────────────────────────────────────────────

    def _make_list(self) -> DropList:
        lw = DropList()
        lw.setSelectionMode(QAbstractItemView.ExtendedSelection)
        lw.dropSignal.connect(self._on_drop)
        return lw

    def _on_drop(self, paths):
        """拖拽文件添加时的回调，归属到当前选中的 tab。"""
        idx = self.tabs.currentIndex()
        lw = [self.merge_list, self.split_list, self.extract_list][idx]
        for p in paths:
            exists = any(lw.item(i).data(Qt.UserRole) == p for i in range(lw.count()))
            if not exists:
                lw.addItem(os.path.basename(p))
                lw.item(lw.count()-1).setData(Qt.UserRole, p)

    def _add_files(self, lw):
        paths, _ = QFileDialog.getOpenFileNames(self, "\u9009\u62e9 PDF \u6587\u4ef6", "", "PDF (*.pdf)")
        self._on_drop(paths)

    def _rem_sel(self, lw):
        for item in lw.selectedItems():
            lw.takeItem(lw.row(item))

    def _get_files(self, lw):
        return [lw.item(i).data(Qt.UserRole) for i in range(lw.count())]

    def _file_section(self, label, list_ref_name):
        """创建文件列表区域，list_ref_name 是属性名，用于保存列表引用。"""
        f = QFrame(); f.setObjectName("panel")
        vl = QVBoxLayout(f); vl.setContentsMargins(12,10,12,10); vl.setSpacing(6)
        lb = QLabel(label)
        lb.setStyleSheet("font-size:15px;font-weight:600;color:#7ac0ff;")
        vl.addWidget(lb)
        lw = self._make_list()
        setattr(self, list_ref_name, lw)
        vl.addWidget(lw)
        hr = QHBoxLayout(); hr.setSpacing(6)
        b1 = QPushButton("\u6dfb\u52a0\u6587\u4ef6"); b1.clicked.connect(lambda: self._add_files(lw)); hr.addWidget(b1)
        b2 = QPushButton("\u79fb\u9664\u6240\u9009"); b2.setObjectName("btnDanger"); b2.clicked.connect(lambda: self._rem_sel(lw)); hr.addWidget(b2)
        b3 = QPushButton("\u6e05\u7a7a\u5217\u8868"); b3.clicked.connect(lw.clear); hr.addWidget(b3)
        hr.addStretch(); vl.addLayout(hr)
        return f

    def _start(self, op, params):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "\u63d0\u793a", "\u6b63\u5728\u5904\u7406\u4e2d\uff0c\u8bf7\u7b49\u5f85")
            return
        self.pbar.setValue(0); self.pbar.setVisible(True)
        self.pstatus.setText("\u51c6\u5907\u4e2d\u2026")
        self._set_btns(False)
        self.worker = PdfWorker(op, params)
        self.worker.progress.connect(lambda p,t: (self.pbar.setValue(p), self.pstatus.setText(t)))
        self.worker.finished.connect(self._on_done)
        self.worker.start()

    def _set_btns(self, on):
        for n in ["merge_btn","split_btn","extract_btn"]:
            b = getattr(self, n, None)
            if b: b.setEnabled(on)

    def _on_done(self, ok, msg):
        self.pbar.setVisible(False)
        self._set_btns(True)
        if ok:
            QMessageBox.information(self, "\u5b8c\u6210", msg)
            out = self.worker.params.get("output") or self.worker.params.get("output_dir")
            if out and os.path.exists(out):
                if os.path.isdir(out): subprocess.Popen(f'explorer "{out}"')
                else: subprocess.Popen(f'explorer /select,"{out}"')
        else:
            QMessageBox.warning(self, "\u5931\u8d25", msg)
        self.pstatus.setText(msg if not ok else "\u5b8c\u6210")

    # ── Tab 1: 合并 ─────────────────────────────────────────────

    def _tab_merge(self):
        w = QWidget(); vl = QVBoxLayout(w); vl.setContentsMargins(10,8,10,8); vl.setSpacing(8)
        vl.addWidget(self._file_section("\u9009\u62e9\u8981\u5408\u5e76\u7684 PDF \u6587\u4ef6\uff08\u62d6\u62fd\u8c03\u6574\u987a\u5e8f\uff09", "merge_list"))
        hr = QHBoxLayout(); hr.setSpacing(6)
        hr.addWidget(QLabel("\u8f93\u51fa\u8def\u5f84:"))
        self.merge_out = QLineEdit(); self.merge_out.setPlaceholderText("\u9ed8\u8ba4: \u684c\u9762/\u5408\u5e76_\u65f6\u95f4\u6233.pdf")
        hr.addWidget(self.merge_out)
        b = QPushButton("\u6d4f\u89c8"); b.setFixedWidth(70)
        b.clicked.connect(lambda: self.merge_out.setText(QFileDialog.getSaveFileName(self, "", "", "PDF (*.pdf)")[0] or self.merge_out.text()))
        hr.addWidget(b); vl.addLayout(hr)
        self.merge_btn = QPushButton("\u5f00\u59cb\u5408\u5e76"); self.merge_btn.setObjectName("btnPrimary")
        self.merge_btn.clicked.connect(self._do_merge)
        vl.addWidget(self.merge_btn)
        return w

    def _do_merge(self):
        files = self._get_files(self.merge_list)
        if len(files) < 2:
            QMessageBox.warning(self, "\u63d0\u793a", "\u8bf7\u9009\u62e9\u81f3\u5c11 2 \u4e2a PDF \u6587\u4ef6"); return
        out = self.merge_out.text().strip()
        if not out:
            out = os.path.join(os.path.expanduser("~"), "Desktop",
                               f"\u5408\u5e76_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
            self.merge_out.setText(out)
        self._start("merge", {"files": files, "output": out})

    # ── Tab 2: 拆分 ─────────────────────────────────────────────

    def _tab_split(self):
        w = QWidget(); vl = QVBoxLayout(w); vl.setContentsMargins(10,8,10,8); vl.setSpacing(8)
        vl.addWidget(self._file_section("\u9009\u62e9\u8981\u62c6\u5206\u7684 PDF \u6587\u4ef6", "split_list"))
        hr = QHBoxLayout(); hr.setSpacing(6)
        hr.addWidget(QLabel("\u8f93\u51fa\u6587\u4ef6\u5939:"))
        self.split_out = QLineEdit(); self.split_out.setPlaceholderText("\u9ed8\u8ba4: \u684c\u9762/\u62c6\u5206_\u65f6\u95f4\u6233")
        hr.addWidget(self.split_out)
        b = QPushButton("\u6d4f\u89c8"); b.setFixedWidth(70)
        b.clicked.connect(lambda: self.split_out.setText(QFileDialog.getExistingDirectory(self) or self.split_out.text()))
        hr.addWidget(b); vl.addLayout(hr)
        self.split_btn = QPushButton("\u5f00\u59cb\u62c6\u5206"); self.split_btn.setObjectName("btnPrimary")
        self.split_btn.clicked.connect(self._do_split)
        vl.addWidget(self.split_btn)
        return w

    def _do_split(self):
        files = self._get_files(self.split_list)
        if not files:
            QMessageBox.warning(self, "\u63d0\u793a", "\u8bf7\u9009\u62e9\u81f3\u5c11 1 \u4e2a PDF \u6587\u4ef6"); return
        out = self.split_out.text().strip()
        if not out:
            out = os.path.join(os.path.expanduser("~"), "Desktop",
                               f"\u62c6\u5206_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(out, exist_ok=True)
        self.split_out.setText(out)
        self._start("split", {"files": files, "output_dir": out})

    # ── Tab 3: 提取 ─────────────────────────────────────────────

    def _tab_extract(self):
        w = QWidget(); vl = QVBoxLayout(w); vl.setContentsMargins(10,8,10,8); vl.setSpacing(8)
        vl.addWidget(self._file_section("\u9009\u62e9\u8981\u63d0\u53d6\u9875\u9762\u7684 PDF \u6587\u4ef6", "extract_list"))
        vl.addWidget(QLabel("\u9875\u7801\u8303\u56f4\uff08\u4f8b\u5982: 1-3,5,7-9\uff09"))
        self.pages_inp = QLineEdit(); self.pages_inp.setPlaceholderText("1-3,5,7-9")
        vl.addWidget(self.pages_inp)
        hr = QHBoxLayout(); hr.setSpacing(6)
        hr.addWidget(QLabel("\u8f93\u51fa\u8def\u5f84:"))
        self.ext_out = QLineEdit(); self.ext_out.setPlaceholderText("\u9ed8\u8ba4: \u684c\u9762/\u63d0\u53d6_\u65f6\u95f4\u6233.pdf")
        hr.addWidget(self.ext_out)
        b = QPushButton("\u6d4f\u89c8"); b.setFixedWidth(70)
        b.clicked.connect(lambda: self.ext_out.setText(QFileDialog.getSaveFileName(self, "", "", "PDF (*.pdf)")[0] or self.ext_out.text()))
        hr.addWidget(b); vl.addLayout(hr)
        self.extract_btn = QPushButton("\u5f00\u59cb\u63d0\u53d6"); self.extract_btn.setObjectName("btnPrimary")
        self.extract_btn.clicked.connect(self._do_extract)
        vl.addWidget(self.extract_btn)
        return w

    def _do_extract(self):
        files = self._get_files(self.extract_list)
        if not files:
            QMessageBox.warning(self, "\u63d0\u793a", "\u8bf7\u9009\u62e9\u81f3\u5c11 1 \u4e2a PDF \u6587\u4ef6"); return
        txt = self.pages_inp.text().strip()
        if not txt:
            QMessageBox.warning(self, "\u63d0\u793a", "\u8bf7\u8f93\u5165\u9875\u7801\u8303\u56f4"); return
        rng = self._parse(txt)
        if rng is None:
            QMessageBox.warning(self, "\u63d0\u793a", "\u9875\u7801\u8303\u56f4\u683c\u5f0f\u9519\u8bef\uff0c\u4f8b\u5982: 1-3,5,7-9"); return
        rng = [(s-1, e-1) for s,e in rng]
        out = self.ext_out.text().strip()
        if not out:
            out = os.path.join(os.path.expanduser("~"), "Desktop",
                               f"\u63d0\u53d6_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
            self.ext_out.setText(out)
        self._start("extract", {"files": files, "output": out, "ranges": rng})

    @staticmethod
    def _parse(txt):
        try:
            r = []
            for p in txt.split(","):
                p = p.strip()
                if "-" in p:
                    a,b = p.split("-",1); a,b = int(a),int(b)
                    if a<1 or b<a: return None
                    r.append((a,b))
                else:
                    v = int(p)
                    if v<1: return None
                    r.append((v,v))
            return r
        except: return None


# ── 入口 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    fnt = QFont()
    for fn in ["Microsoft YaHei UI","Microsoft YaHei","Segoe UI","PingFang SC","sans-serif"]:
        if fn in QFontDatabase().families(): fnt.setFamily(fn); break
    fnt.setPointSize(10); app.setFont(fnt)
    PdfTool().show()
    sys.exit(app.exec_())

# ── 打包命令 ──────────────────────────────────────────────────────────
# pip install PyMuPDF
# pyinstaller --onefile --windowed --name PDF_Tool --exclude torch --exclude PySide6 --exclude PySide2 main.py
