import sys, os, io, zipfile
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QSlider, QCheckBox, QProgressBar, QFileDialog,
    QMessageBox, QGroupBox, QSplitter, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True
SUPPORTED = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# ============================================================
# Worker
# ============================================================
class CompressWorker(QThread):
    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(list)

    def __init__(self, files, quality):
        super().__init__()
        self.files = files
        self.quality = quality
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        results = []
        total = len(self.files)
        for i, (path, orig_size) in enumerate(self.files):
            if self._cancel:
                return
            name = Path(path).name
            self.progress.emit(i + 1, total, name)
            try:
                if orig_size == 0:
                    results.append((path, 0, False, "空文件"))
                    continue
                img = Image.open(path).convert("RGB")
                buf = io.BytesIO()
                ext = Path(path).suffix.lower()
                fmt = "JPEG" if ext in (".jpg", ".jpeg") else "PNG" if ext == ".png" else "WEBP" if ext == ".webp" else "BMP"
                if fmt == "JPEG" and img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(buf, format=fmt, quality=self.quality, optimize=True)
                results.append((path, buf.tell(), True, None))
            except MemoryError:
                results.append((path, 0, False, "内存不足，请减少图片数量"))
            except Exception as e:
                results.append((path, 0, False, str(e)))
        self.done.emit(results)


# ============================================================
# Main Window
# ============================================================
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.files = []
        self.results = {}
        self.worker = None
        self.init_ui()
        self.apply_styles()

    def init_ui(self):
        self.setWindowTitle("图片批量压缩工具 v1.0")
        self.resize(900, 600)
        self.setMinimumSize(750, 480)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ===== LEFT PANEL =====
        left = QWidget()
        left.setObjectName("panelLeft")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(16, 16, 8, 16)

        title_l = QLabel("文件列表")
        title_l.setObjectName("panelTitle")

        self.file_list = QListWidget()
        self.file_list.setSpacing(3)
        self.file_list.itemSelectionChanged.connect(self._on_sel)

        tb = QHBoxLayout()
        tb.setSpacing(6)
        self.btn_add = QPushButton("添加文件")
        self.btn_del = QPushButton("移除")
        self.btn_clr = QPushButton("清空")
        for b in (self.btn_add, self.btn_del, self.btn_clr):
            b.setObjectName("toolBtn")
        self.btn_del.setEnabled(False)
        self.btn_clr.setEnabled(False)
        tb.addWidget(self.btn_add)
        tb.addWidget(self.btn_del)
        tb.addWidget(self.btn_clr)

        lv.addWidget(title_l)
        lv.addWidget(self.file_list)
        lv.addLayout(tb)

        # ===== RIGHT PANEL =====
        right = QWidget()
        right.setObjectName("panelRight")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 16, 16, 16)
        rv.setSpacing(12)

        # Settings
        sg = QGroupBox("压缩设置")
        sg.setObjectName("settingsGroup")
        sv = QVBoxLayout(sg)
        sv.setSpacing(10)

        sq = QHBoxLayout()
        sq.setSpacing(12)
        ql = QLabel("质量:")
        ql.setObjectName("label")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(1, 100)
        self.slider.setValue(85)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(10)
        self.val_label = QLabel("85")
        self.val_label.setObjectName("valueBadge")
        sq.addWidget(ql)
        sq.addWidget(self.slider)
        sq.addWidget(self.val_label)
        self.slider.valueChanged.connect(lambda v: self.val_label.setText(str(v)))
        sv.addLayout(sq)

        # Info
        ig = QGroupBox("压缩信息")
        ig.setObjectName("infoGroup")
        iv = QVBoxLayout(ig)
        iv.setSpacing(6)

        def info_row(label, obj):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(4, 2, 4, 2)
            l = QLabel(label)
            l.setObjectName("infoLabel")
            v = QLabel("--")
            v.setObjectName(obj)
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            h.addWidget(l)
            h.addWidget(v)
            return w

        self.r_orig = info_row("原始大小", "infoVal")
        self.r_comp = info_row("压缩后", "infoVal")
        self.r_save = info_row("节省空间", "infoValGood")
        iv.addWidget(self.r_orig)
        iv.addWidget(self.r_comp)
        iv.addWidget(self.r_save)

        # Buttons
        self.btn_compress = QPushButton("开始压缩")
        self.btn_compress.setObjectName("primaryBtn")
        self.btn_compress.setEnabled(False)

        self.pbar = QProgressBar()
        self.pbar.setObjectName("progressBar")
        self.pbar.setVisible(False)

        self.btn_zip = QPushButton("导出 ZIP")
        self.btn_zip.setObjectName("secondaryBtn")
        self.btn_zip.setEnabled(False)

        self.chk_top = QCheckBox("总在最前")
        self.chk_top.setObjectName("topCheck")

        rv.addWidget(sg)
        rv.addWidget(ig)
        rv.addWidget(self.btn_compress)
        rv.addWidget(self.pbar)
        rv.addWidget(self.btn_zip)
        rv.addStretch()
        rv.addWidget(self.chk_top)

        # Splitter
        sp = QSplitter(Qt.Horizontal)
        sp.addWidget(left)
        sp.addWidget(right)
        sp.setStretchFactor(0, 3)
        sp.setStretchFactor(1, 2)
        sp.setHandleWidth(1)
        root.addWidget(sp)

        # Signals
        self.btn_add.clicked.connect(self.add_files)
        self.btn_del.clicked.connect(self.remove_sel)
        self.btn_clr.clicked.connect(self.clear_all)
        self.btn_compress.clicked.connect(self.start_compress)
        self.btn_zip.clicked.connect(self.export_zip)
        self.chk_top.stateChanged.connect(self._toggle_top)

    def apply_styles(self):
        self.setStyleSheet("""
            QWidget { font-family: "Segoe UI", "Microsoft YaHei", sans-serif; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; color: #111; }
            QWidget#panelLeft { background: #FAFAFA; }
            QWidget#panelRight { background: #FFFFFF; }
            QLabel#panelTitle { param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; font-weight: 700; color: #111; padding: 0 0 8 0; }
            QListWidget { background: #FFF; border: 1px solid #D0D0D0; border-radius: 5px; padding: 4px; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; }
            QListWidget::item { padding: 6px 10px; border-radius: 3px; }
            QListWidget::item:selected { background: #0078D4; color: #FFF; }
            QListWidget::item:hover:!selected { background: #EBEBEB; }
            QPushButton { background: #FFF; border: 1px solid #D0D0D0; border-radius: 5px; padding: 6px 16px; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; font-weight: 600; }
            QPushButton:hover { background: #E8E8E8; border-color: #0078D4; }
            QPushButton:disabled { color: #666; background: #F5F5F5; border-color: #E0E0E0; }
            QPushButton#toolBtn { param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; padding: 6px 14px; }
            QGroupBox { font-weight: 700; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; color: #111; border: 1px solid #D0D0D0; border-radius: 6px; margin-top: 14px; padding: 20px 12px 12px 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; color: #111; }
            QLabel#label { font-weight: 600; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; color: #333; }
            QLabel#valueBadge { font-weight: 700; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; color: #0078D4; min-width: 36px; text-align: center; }
            QLabel#infoLabel { param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; color: #333; }
            QLabel#infoVal { param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; font-weight: 600; color: #111; }
            QLabel#infoValGood { param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; font-weight: 700; color: #2E7D32; }
            QSlider::groove:horizontal { height: 6px; background: #E0E0E0; border-radius: 3px; }
            QSlider::handle:horizontal { background: #0078D4; width: 22px; height: 22px; margin: -8px 0; border-radius: 11px; }
            QSlider::sub-page:horizontal { background: #0078D4; border-radius: 3px; }
            QPushButton#primaryBtn { background: #0078D4; color: #FFF; border: none; border-radius: 5px; padding: 12px; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; font-weight: 700; }
            QPushButton#primaryBtn:hover { background: #106EBE; }
            QPushButton#primaryBtn:disabled { background: #B0B0B0; color: #DDD; }
            QPushButton#secondaryBtn { background: #FFF; color: #111; border: 1px solid #D0D0D0; border-radius: 5px; padding: 10px; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; font-weight: 600; }
            QPushButton#secondaryBtn:hover { background: #E8E8E8; border-color: #0078D4; }
            QPushButton#secondaryBtn:disabled { color: #666; background: #F5F5F5; border-color: #E0E0E0; }
            QProgressBar { border: 1px solid #D0D0D0; border-radius: 4px; text-align: center; color: #111; background: #FFF; height: 24px; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; font-weight: 600; }
            QProgressBar::chunk { background: #0078D4; border-radius: 3px; }
            QCheckBox { spacing: 8px; param($m) $v = [int]$m.Groups[1].Value; if ($v -lt 14) {"font-size: 14pt"} else {"font-size: ${v}pt"}; font-weight: 600; color: #111; }
            QCheckBox::indicator { width: 18px; height: 18px; border: 2px solid #B0B0B0; border-radius: 3px; }
            QCheckBox::indicator:checked { background: #0078D4; border-color: #0078D4; }
            QSplitter::handle { background: #E0E0E0; }
        """)

    # ---- File mgmt ----
    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择图片", "",
            "图片文件 (*.jpg *.jpeg *.png *.bmp *.webp);;所有文件 (*.*)")
        for p in paths:
            if any(f[0] == p for f in self.files):
                continue
            try:
                sz = os.path.getsize(p)
                self.files.append((p, sz))
                self.file_list.addItem(f"{Path(p).name}  ({self._fmt(sz)})")
            except:
                pass
        self._refresh()

    def remove_sel(self):
        for item in self.file_list.selectedItems():
            idx = self.file_list.row(item)
            path = self.files[idx][0]
            self.files.pop(idx)
            self.results.pop(path, None)
            self.file_list.takeItem(idx)
        self._refresh()

    def clear_all(self):
        self.files.clear()
        self.results.clear()
        self.file_list.clear()
        self._refresh()

    def _on_sel(self):
        self.btn_del.setEnabled(len(self.file_list.selectedItems()) > 0)

    def _refresh(self):
        n = len(self.files)
        busy = self.worker and self.worker.isRunning()
        self.btn_clr.setEnabled(n > 0 and not busy)
        self.btn_compress.setEnabled(n > 0 and not busy)
        self.btn_zip.setEnabled(bool(self.results) and not busy)
        total = sum(s for _, s in self.files)
        orig = self.r_orig.findChild(QLabel, "infoVal")
        orig.setText(f"{n} 张图片，共 {self._fmt(total)}" if n else "0 张图片")
        comp = self.r_comp.findChild(QLabel, "infoVal")
        save = self.r_save.findChild(QLabel, "infoValGood")
        if self.results:
            ok = [v for v in self.results.values() if v[1] > 0]
            if ok:
                ot = sum(v[0] for v in ok)
                ct = sum(v[1] for v in ok)
                sv = ot - ct
                pct = (sv / ot * 100) if ot > 0 else 0
                comp.setText(self._fmt(ct))
                save.setText(f"{self._fmt(sv)} ({pct:.1f}%)")
                return
        comp.setText("--")
        save.setText("--")

    def _fmt(self, b):
        if b < 1024:
            return f"{b} B"
        if b < 1048576:
            return f"{b/1024:.1f} KB"
        return f"{b/1048576:.2f} MB"

    def _toggle_top(self, state):
        flags = self.windowFlags()
        if state == Qt.Checked:
            self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
        self.show()

    # ---- Compress ----
    def start_compress(self):
        if not self.files:
            return
        self.results = {}
        q = self.slider.value()
        self.worker = CompressWorker(list(self.files), q)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.pbar.setVisible(True)
        self.pbar.setValue(0)
        self.pbar.setMaximum(len(self.files))
        self.pbar.setFormat("准备中...")
        self.btn_compress.setEnabled(False)
        self.btn_compress.setText("压缩中...")
        self._refresh()
        self.worker.start()

    def _on_progress(self, current, total, name):
        self.pbar.setValue(current)
        self.pbar.setFormat(f"正在处理: {name}  ({current}/{total})")

    def _on_done(self, results):
        errors = []
        for path, comp, ok, err in results:
            orig = next((s for p, s in self.files if p == path), 0)
            self.results[path] = (orig, comp, ok, err)
            if not ok:
                errors.append(f"{Path(path).name}: {err}")
        self.pbar.setVisible(False)
        self.btn_compress.setText("开始压缩")
        self._refresh()

        msg = f"压缩完成！共处理 {len(results)} 张图片"
        if errors:
            msg += "\n\n以下图片处理失败:\n" + "\n".join(errors[:5])
            if len(errors) > 5:
                msg += f"\n...及其他 {len(errors)-5} 张"
        QMessageBox.information(self, "完成", msg)

    # ---- Export ZIP ----
    def export_zip(self):
        ok = [(p, v) for p, v in self.results.items() if v[1] > 0]
        if not ok:
            QMessageBox.warning(self, "提示", "没有可导出的压缩图片")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存 ZIP", "compressed_images.zip", "ZIP 文件 (*.zip)")
        if not path:
            return
        try:
            self.btn_zip.setEnabled(False)
            self.btn_zip.setText("正在打包...")
            QApplication.processEvents()
            q = self.slider.value()
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fpath, (orig, comp, ok_flag, err) in ok:
                    if ok_flag:
                        name = Path(fpath).name
                        img = Image.open(fpath).convert("RGB")
                        buf = io.BytesIO()
                        ext = Path(fpath).suffix.lower()
                        fmt = "JPEG" if ext in (".jpg", ".jpeg") else "PNG" if ext == ".png" else "WEBP" if ext == ".webp" else "BMP"
                        img.save(buf, format=fmt, quality=q, optimize=True)
                        zf.writestr(name, buf.getvalue())
            QMessageBox.information(self, "成功", f"已导出到:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {e}")
        finally:
            self.btn_zip.setText("导出 ZIP")
            self._refresh()


# ============================================================
# Entry
# ============================================================
if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("imgcompressor")
    except:
        pass
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
