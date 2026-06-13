# -*- coding: utf-8 -*-
"""CSV/Excel 数据清洗 & 格式互转工具 - 极致性能版"""
import sys, os, re, time, traceback
import pandas as pd
import numpy as np
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QCheckBox, QRadioButton,
    QComboBox, QFileDialog, QMessageBox, QTableView, QTextEdit,
    QProgressBar, QGroupBox, QHeaderView, QGridLayout)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QTextCursor, QStandardItemModel, QStandardItem

HAS_NUMBA = False
try:
    from numba import jit, prange
    HAS_NUMBA = True
except:
    def jit(**kw): return lambda f: f
    prange = range

if HAS_NUMBA:
    @jit(nopython=True, nogil=True, cache=True)
    def _fast_contains(arr, pattern_bytes):
        out = np.empty(len(arr), dtype=np.bool_)
        for i in prange(len(arr)):
            s = arr[i]
            if isinstance(s, float) and str(s) == "nan": out[i] = False
            else:
                try:
                    val = str(s).encode("utf-8") if not isinstance(s, bytes) else s
                    out[i] = pattern_bytes in val
                except: out[i] = False
        return out

    @jit(nopython=True, nogil=True, cache=True)
    def _fast_numeric_check(arr):
        out = np.empty(len(arr), dtype=np.bool_)
        for i in prange(len(arr)):
            v = arr[i]
            if isinstance(v, (int, float, np.integer, np.floating)):
                out[i] = not (isinstance(v, float) and str(v) == "nan")
            elif isinstance(v, str):
                s = v.strip()
                if not s: out[i] = False
                else:
                    try: float(s); out[i] = True
                    except: out[i] = False
            else: out[i] = False
        return out

def _process_chunk(args):
    chunk_path, ops, chunk_idx = args
    try:
        df = pd.read_pickle(chunk_path)
        for op_name, op_params in ops:
            if op_name == "drop_duplicates":
                df = df.drop_duplicates(subset=op_params.get("subset", None))
            elif op_name == "drop_empty_rows":
                df = df.dropna(how="all", subset=op_params.get("subset", None))
            elif op_name == "drop_na":
                df = df.dropna()
            elif op_name == "filter_keyword":
                col, pat = op_params["column"], op_params["pattern"]
                keep = op_params.get("keep", True)
                regex = op_params.get("regex", False)
                if col in df.columns:
                    mask = df[col].astype(str).str.contains(pat, na=False, regex=regex)
                    df = df[mask if keep else ~mask]
            elif op_name == "convert_types":
                for col, dtype in op_params.get("conversions", {}).items():
                    if col in df.columns:
                        try:
                            if dtype == "number": df[col] = pd.to_numeric(df[col], errors="coerce")
                            elif dtype == "date": df[col] = pd.to_datetime(df[col], errors="coerce")
                        except: pass
        result_path = chunk_path + ".processed"
        df.to_pickle(result_path)
        return (chunk_idx, len(df))
    except Exception as e:
        return (chunk_idx, -1)


class DataCleaner:
    @staticmethod
    def load_file(path, encoding=None, nrows=None):
        ext = Path(path).suffix.lower()
        encoding = encoding or DataCleaner.detect_encoding(path)
        if ext in (".xls", ".xlsx"):
            df = pd.read_excel(path, engine="openpyxl" if ext==".xlsx" else "xlrd", nrows=nrows)
            return df, encoding
        try:
            sep = DataCleaner.detect_separator(path, encoding)
            df = pd.read_csv(path, sep=sep, encoding=encoding, nrows=nrows, low_memory=False, on_bad_lines="warn")
            return df, encoding
        except:
            for enc in ["utf-8", "gbk", "gb2312", "latin-1"]:
                try:
                    df = pd.read_csv(path, encoding=enc, nrows=nrows)
                    return df, enc
                except: continue
            raise

    @staticmethod
    def detect_encoding(path):
        try:
            import chardet
            with open(path, "rb") as f:
                raw = f.read(min(100000, 1024*1024))
            return (chardet.detect(raw).get("encoding") or "utf-8")
        except: return "utf-8"

    @staticmethod
    def detect_separator(path, encoding="utf-8"):
        try:
            with open(path, "r", encoding=encoding) as f:
                first = f.readline()
            best, best_c = ",", 0
            for sep in [",", ";", "\t", "|"]:
                c = first.count(sep)
                if c > best_c: best, best_c = sep, c
            return best
        except: return ","

    @staticmethod
    def drop_duplicates(df, subset=None):
        before = len(df)
        return df.drop_duplicates(subset=subset), before - len(df)

    @staticmethod
    def drop_empty_rows(df, subset=None):
        before = len(df)
        return df.dropna(how="all", subset=subset), before - len(df)

    @staticmethod
    def drop_na(df):
        before = len(df)
        return df.dropna(), before - len(df)

    @staticmethod
    def filter_keyword(df, column, pattern, keep=True, regex=False):
        before = len(df)
        if column not in df.columns: return df, 0
        mask = df[column].astype(str).str.contains(pattern, na=False, regex=regex)
        return (df[mask if keep else ~mask]), before - len(df)

    @staticmethod
    def convert_types(df, conversions):
        report = {}
        for col, dtype in conversions.items():
            if col not in df.columns: continue
            try:
                before = str(df[col].dtype)
                if dtype == "number": df[col] = pd.to_numeric(df[col], errors="coerce")
                elif dtype == "date": df[col] = pd.to_datetime(df[col], errors="coerce")
                elif dtype == "string": df[col] = df[col].astype(str)
                elif dtype == "int": df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
                report[col] = f"{before} -> {df[col].dtype}"
            except Exception as e: report[col] = f"error: {e}"
        return df, report


class Worker(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, work_type, **kw):
        super().__init__()
        self.wt = work_type
        self.kw = kw
        self._cancel = False

    def cancel(self): self._cancel = True

    def run(self):
        try:
            {"preview": self._preview, "clean": self._clean,
             "csv2xlsx": self._csv2xlsx, "xlsx2csv": self._xlsx2csv}[self.wt]()
        except Exception as e:
            if not self._cancel: self.error.emit(traceback.format_exc())

    def _preview(self):
        path = self.kw["path"]
        self.log.emit(f"[信息] 加载: {path}")
        df, enc = DataCleaner.load_file(path, self.kw.get("encoding"))
        self.log.emit(f"[信息] 加载完成: {len(df)} 行 x {len(df.columns)} 列")
        self.finished.emit({"type":"preview","df":df,"encoding":enc,"shape":(len(df),len(df.columns))})

    def _clean(self):
        df = self.kw["df"]
        ops = self.kw["ops"]
        use_parallel = self.kw.get("use_parallel", False) and len(df) > 50000
        self.log.emit(f"[信息] 清洗开始, 原始: {len(df)} 行")

        if use_parallel:
            self.log.emit("[信息] 多进程分块处理")
            result = self._parallel_clean(df, ops)
            if result: df, total_removed = result
            else: return
        else:
            total_removed = 0
            for idx, (op_name, op_params) in enumerate(ops):
                if self._cancel: return
                try:
                    if op_name == "drop_duplicates":
                        df, r = DataCleaner.drop_duplicates(df, op_params.get("subset"))
                        total_removed += r; self.log.emit(f"  [清洗] 去重: 移除 {r} 行")
                    elif op_name == "drop_empty_rows":
                        df, r = DataCleaner.drop_empty_rows(df, op_params.get("subset"))
                        total_removed += r; self.log.emit(f"  [清洗] 去空行: 移除 {r} 行")
                    elif op_name == "drop_na":
                        df, r = DataCleaner.drop_na(df)
                        total_removed += r; self.log.emit(f"  [清洗] 去NaN: 移除 {r} 行")
                    elif op_name == "filter_keyword":
                        df, r = DataCleaner.filter_keyword(df, op_params["column"], op_params["pattern"],
                            op_params.get("keep",True), op_params.get("regex",False))
                        total_removed += r; self.log.emit(f"  [清洗] 筛选: 移除 {r} 行")
                    elif op_name == "convert_types":
                        df, report = DataCleaner.convert_types(df, op_params.get("conversions",{}))
                        for col, r2 in report.items(): self.log.emit(f"  [清洗] {col}: {r2}")
                except Exception as e:
                    self.log.emit(f"  [错误] {op_name}: {e}")
                self.progress.emit(idx+1, len(ops))

        r = {"type":"clean","df":df,"removed":total_removed}
        self.log.emit(f"[完成] 清洗完成: {len(df)} 行 (移除 {total_removed})")
        self.finished.emit(r)

    def _parallel_clean(self, df, ops):
        import tempfile, shutil
        from concurrent.futures import ProcessPoolExecutor, as_completed
        tmpdir = tempfile.mkdtemp(prefix="csvc_")
        try:
            chunks = []
            cs = 25000
            for i in range(0, len(df), cs):
                cp = os.path.join(tmpdir, f"c{i//cs:06d}.pkl")
                df.iloc[i:i+cs].to_pickle(cp)
                chunks.append((cp, ops, i//cs))
            n = len(chunks)
            self.log.emit(f"[信息] {n} 块, 启动进程池...")
            results = [None]*n
            with ProcessPoolExecutor(max_workers=min(os.cpu_count() or 4, 8)) as ex:
                fs = {ex.submit(_process_chunk, c):c[2] for c in chunks}
                for f in as_completed(fs):
                    idx, cnt = f.result()
                    results[idx] = cnt
                    self.progress.emit(idx+1, n)
            pcs = []
            tr = 0
            for i, cp in enumerate(chunks):
                rp = cp[0]+".processed"
                if os.path.exists(rp):
                    pcs.append(pd.read_pickle(rp))
                    tr += len(pd.read_pickle(cp[0])) - results[i]
                try: os.unlink(cp[0])
                except: pass
                try: os.unlink(rp)
                except: pass
            if pcs:
                return pd.concat(pcs, ignore_index=True), tr
        finally:
            try: shutil.rmtree(tmpdir)
            except: pass

    def _csv2xlsx(self):
        csv_path, xlsx_path = self.kw["csv_path"], self.kw["xlsx_path"]
        enc, sep = self.kw.get("encoding","utf-8"), self.kw.get("sep",",")
        writer = pd.ExcelWriter(xlsx_path, engine="openpyxl")
        try:
            total = 0; first = True
            for i, chunk in enumerate(pd.read_csv(csv_path, sep=sep, encoding=enc, chunksize=10000, low_memory=False)):
                if first:
                    chunk.to_excel(writer, sheet_name="Sheet1", index=False)
                    first = False
                else:
                    chunk.to_excel(writer, sheet_name="Sheet1", index=False, startrow=total, header=False)
                total += len(chunk)
                self.progress.emit(i+1, total)
            writer.close()
            self.log.emit(f"[完成] CSV->Excel: {total} 行")
            self.finished.emit({"type":"convert","total":total})
        except:
            writer.close(); raise

    def _xlsx2csv(self):
        xlsx_path, csv_path = self.kw["xlsx_path"], self.kw["csv_path"]
        enc, sep = self.kw.get("encoding","utf-8"), self.kw.get("sep",",")
        df = pd.read_excel(xlsx_path, engine="openpyxl")
        df.to_csv(csv_path, encoding=enc, sep=sep, index=False)
        self.log.emit(f"[完成] Excel->CSV: {len(df)} 行")
        self.finished.emit({"type":"convert","total":len(df)})


class PandasModel(QStandardItemModel):
    def __init__(self, df):
        super().__init__()
        self._df = df
        nrows = min(len(df), 100)
        self.setColumnCount(len(df.columns))
        self.setRowCount(nrows)
        self.setHorizontalHeaderLabels(list(df.columns.astype(str)))
        for r in range(nrows):
            for c in range(len(df.columns)):
                v = df.iloc[r, c]
                item = QStandardItem(str(v) if not pd.isna(v) else "")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.setItem(r, c, item)

    def dataframe(self): return self._df


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.df = self.file_path = self.file_enc = self.worker = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("CSV/Excel 数据清洗 & 互转工具")
        self.resize(1000, 700)
        self.setMinimumSize(800, 500)
        c = QWidget(); self.setCentralWidget(c)
        m = QVBoxLayout(c); m.setSpacing(8); m.setContentsMargins(12,12,12,12)

        # Toolbar
        tb = QHBoxLayout(); tb.setSpacing(8)
        self.btn_open = QPushButton(chr(0x1F4C2)+" 打开文件"); self.btn_open.clicked.connect(self.open_file)
        self.btn_save = QPushButton(chr(0x1F4BE)+" 导出"); self.btn_save.clicked.connect(self.save_file); self.btn_save.setEnabled(False)
        self.chk_top = QCheckBox("总在最前"); self.chk_top.stateChanged.connect(self._top)
        self.chk_para = QCheckBox("多进程加速"); self.chk_para.setChecked(True)
        for w in [self.btn_open, self.btn_save]: w.setMinimumHeight(38)
        tb.addWidget(self.btn_open); tb.addWidget(self.btn_save); tb.addStretch()
        tb.addWidget(self.chk_para); tb.addWidget(self.chk_top); m.addLayout(tb)

        # Options
        og = QGroupBox("数据清洗选项")
        ol = QGridLayout(og); ol.setSpacing(6)
        self.c_dup = QCheckBox("删除重复行"); self.c_dup.setChecked(True)
        self.c_emp = QCheckBox("删除空行"); self.c_emp.setChecked(True)
        self.c_na = QCheckBox("删除含NaN行")
        ol.addWidget(self.c_dup,0,0); ol.addWidget(self.c_emp,0,1); ol.addWidget(self.c_na,0,2)

        fl = QHBoxLayout()
        fl.addWidget(QLabel("关键词筛选:"))
        self.e_fcol = QLineEdit(); self.e_fcol.setPlaceholderText("列名")
        self.e_fpat = QLineEdit(); self.e_fpat.setPlaceholderText("关键词/正则")
        self.r_keep = QRadioButton("保留"); self.r_keep.setChecked(True)
        self.r_del = QRadioButton("删除")
        self.c_re = QCheckBox("正则")
        for w in [self.e_fcol, self.e_fpat]: w.setMinimumWidth(90)
        fl.addWidget(self.e_fcol); fl.addWidget(self.e_fpat)
        fl.addWidget(self.r_keep); fl.addWidget(self.r_del); fl.addWidget(self.c_re); fl.addStretch()
        ol.addLayout(fl,1,0,1,3)

        cg = QGroupBox("格式转换")
        cl = QGridLayout(cg); cl.setSpacing(6)
        self.b_c2x = QPushButton("CSV -> Excel"); self.b_c2x.clicked.connect(lambda: self._conv("csv2xlsx"))
        self.b_x2c = QPushButton("Excel -> CSV"); self.b_x2c.clicked.connect(lambda: self._conv("xlsx2csv"))
        self.combo_enc = QComboBox(); self.combo_enc.addItems(["utf-8","gbk","gb2312","latin-1","utf-16"])
        self.combo_sep = QComboBox(); self.combo_sep.addItems([",",";","\\t","|"])
        cl.addWidget(self.b_c2x,0,0); cl.addWidget(self.b_x2c,0,1)
        cl.addWidget(QLabel("编码:"),1,0); cl.addWidget(self.combo_enc,1,1)
        cl.addWidget(QLabel("分隔符:"),2,0); cl.addWidget(self.combo_sep,2,1)
        cl.setColumnStretch(2,1)

        oh = QHBoxLayout(); oh.addWidget(og,2); oh.addWidget(cg,1); m.addLayout(oh)

        self.b_clean = QPushButton(chr(0x25B6)+" 执行清洗")
        self.b_clean.clicked.connect(self.run_clean); self.b_clean.setMinimumHeight(42); self.b_clean.setEnabled(False)
        self.b_preview = QPushButton("预览前100行")
        self.b_preview.clicked.connect(self._preview); self.b_preview.setEnabled(False)
        eh = QHBoxLayout(); eh.addWidget(self.b_preview); eh.addStretch(); eh.addWidget(self.b_clean)
        m.addLayout(eh)

        self.status = QLabel("就绪 - 请打开CSV或Excel文件")
        self.status.setStyleSheet("color:#333;font-size:13pt")
        m.addWidget(self.status)

        self.tv = QTableView()
        self.tv.setAlternatingRowColors(True)
        self.tv.horizontalHeader().setStretchLastSection(True)
        self.tv.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.tv.setSelectionBehavior(QTableView.SelectRows)
        self.tv.setSortingEnabled(True)
        m.addWidget(self.tv, 1)

        self.pb = QProgressBar(); self.pb.setVisible(False); self.pb.setMinimumHeight(22)
        m.addWidget(self.pb)

        self.log = QTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(150)
        self.log.setStyleSheet("QTextEdit{background:#1E1E1E;color:#FFF;font:12pt Consolas;border:2px solid #CCC;border-radius:4px;padding:6px}")
        m.addWidget(self.log)
        self._log("[系统] 启动完成，请打开文件开始操作")
        self._style()

    def _style(self):
        self.setStyleSheet("""
            QMainWindow,QWidget{background:#FFF}
            QGroupBox{font-size:15pt;font-weight:bold;color:#000;border:2px solid #CCC;border-radius:6px;margin-top:12px;padding:16px 12px 12px}
            QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;padding:2px 8px;background:#FFF}
            QLabel{font-size:14pt;color:#000}
            QPushButton{font-size:14pt;font-weight:bold;color:#FFF;background:#0078D4;border:none;border-radius:6px;padding:8px 20px;min-height:36px}
            QPushButton:hover{background:#106EBE}
            QPushButton:disabled{background:#CCC;color:#888}
            QCheckBox,QRadioButton{font-size:14pt;color:#000;spacing:6px}
            QCheckBox::indicator,QRadioButton::indicator{width:20px;height:20px}
            QLineEdit,QComboBox{font-size:14pt;color:#000;background:#FFF;border:2px solid #CCC;border-radius:4px;padding:4px 8px;min-height:32px}
            QLineEdit:focus,QComboBox:focus{border:3px solid #0078D4}
            QTableView{font-size:13pt;color:#000;background:#FFF;border:2px solid #CCC;border-radius:4px;gridline-color:#E0E0E0}
            QTableView::item{padding:4px 8px}
            QTableView::item:selected{background:#0078D4;color:#FFF}
            QHeaderView::section{font-size:13pt;font-weight:bold;color:#000;background:#F0F0F0;border:1px solid #DDD;padding:6px 8px}
            QProgressBar{font-size:12pt;color:#FFF;text-align:center;border:1px solid #CCC;border-radius:4px;background:#F0F0F0}
            QProgressBar::chunk{background:#0078D4;border-radius:3px}
        """)

    def _top(self, s):
        f = self.windowFlags()
        self.setWindowFlags(f | Qt.WindowStaysOnTopHint if s==Qt.Checked else f & ~Qt.WindowStaysOnTopHint)
        self.show()

    def _log(self, t):
        self.log.append(t)
        c = self.log.textCursor(); c.movePosition(QTextCursor.End); self.log.setTextCursor(c)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开文件", "",
            "支持格式 (*.csv *.xlsx *.xls);;CSV (*.csv);;Excel (*.xlsx *.xls);;所有文件 (*.*)")
        if not path: return
        self.file_path = path
        self._log(f"[信息] 打开: {path}")
        self.btn_open.setEnabled(False)
        self.pb.setVisible(True); self.pb.setRange(0,0)
        self.worker = Worker("preview", path=path)
        self.worker.log.connect(self._log)
        self.worker.finished.connect(self._on_preview)
        self.worker.error.connect(self._on_err)
        self.worker.start()

    def _on_preview(self, r):
        if r["type"]=="preview":
            self.df, self.file_enc = r["df"], r["encoding"]
            self.tv.setModel(PandasModel(self.df))
            self.status.setText(f"已加载: {r['shape'][0]} 行 x {r['shape'][1]} 列 | 编码: {self.file_enc}")
            self.btn_save.setEnabled(True); self.b_clean.setEnabled(True); self.b_preview.setEnabled(True)
        self.btn_open.setEnabled(True); self.pb.setVisible(False)

    def _preview(self):
        if self.df is None or self.df.empty:
            QMessageBox.warning(self,"提示","没有数据")
            return
        self.tv.setModel(PandasModel(self.df))
        self._log(f"[信息] 预览 {min(100,len(self.df))} 行")

    def run_clean(self):
        if self.df is None or self.df.empty: QMessageBox.warning(self,"提示","请先打开文件"); return
        ops = []
        if self.c_dup.isChecked(): ops.append(("drop_duplicates",{}))
        if self.c_emp.isChecked(): ops.append(("drop_empty_rows",{}))
        if self.c_na.isChecked(): ops.append(("drop_na",{}))
        col = self.e_fcol.text().strip(); pat = self.e_fpat.text().strip()
        if col and pat: ops.append(("filter_keyword",{"column":col,"pattern":pat,"keep":self.r_keep.isChecked(),"regex":self.c_re.isChecked()}))
        if not ops: QMessageBox.warning(self,"提示","请选择至少一个操作"); return
        self._log(f"[信息] 清洗: {len(ops)} 个操作"); self.b_clean.setEnabled(False)
        self.pb.setVisible(True); self.pb.setRange(0,len(ops)); self.pb.setValue(0)
        self.worker = Worker("clean", df=self.df.copy(), ops=ops, use_parallel=self.chk_para.isChecked())
        self.worker.log.connect(self._log)
        self.worker.progress.connect(lambda c,t: (self.pb.setValue(c),self.pb.setMaximum(t)))
        self.worker.finished.connect(self._on_clean)
        self.worker.error.connect(self._on_err)
        self.worker.start()

    def _on_clean(self, r):
        if r["type"]=="clean":
            self.df = r["df"]
            self.tv.setModel(PandasModel(self.df))
            self.status.setText(f"清洗完成: {len(self.df)} 行 (移除 {r['removed']})")
        self.b_clean.setEnabled(True); self.pb.setVisible(False)

    def _on_err(self, msg):
        self.btn_open.setEnabled(True); self.b_clean.setEnabled(True); self.pb.setVisible(False)
        self._log(f"[错误] {msg}"); QMessageBox.critical(self,"错误",f"失败:\n\n{msg[:500]}")

    def save_file(self):
        if self.df is None or self.df.empty: QMessageBox.warning(self,"提示","没有数据"); return
        path, _ = QFileDialog.getSaveFileName(self,"导出文件","cleaned_data","CSV (*.csv);;Excel (*.xlsx);;所有文件 (*.*)")
        if not path: return
        ext = Path(path).suffix.lower()
        try:
            if ext==".csv":
                self.df.to_csv(path, encoding=self.combo_enc.currentText(), sep=self.combo_sep.currentText().replace("\\t","\t"), index=False)
            elif ext==".xlsx":
                self.df.to_excel(path, engine="openpyxl", index=False)
            else: self.df.to_csv(path, index=False)
            self._log(f"[完成] 导出: {path}"); QMessageBox.information(self,"成功",f"导出完成:\n{path}")
        except Exception as e: QMessageBox.critical(self,"错误",f"导出失败: {e}"); self._log(f"[错误] 导出: {e}")

    def _conv(self, mode):
        if mode=="csv2xlsx":
            p,_ = QFileDialog.getOpenFileName(self,"选择CSV","","CSV (*.csv)")
            if not p: return
            s,_ = QFileDialog.getSaveFileName(self,"保存Excel","","Excel (*.xlsx)")
            if not s: return
            self.b_c2x.setEnabled(False)
            self.worker = Worker("csv2xlsx", csv_path=p, xlsx_path=s,
                encoding=self.combo_enc.currentText(), sep=self.combo_sep.currentText().replace("\\t","\t"))
        else:
            p,_ = QFileDialog.getOpenFileName(self,"选择Excel","","Excel (*.xlsx *.xls)")
            if not p: return
            s,_ = QFileDialog.getSaveFileName(self,"保存CSV","","CSV (*.csv)")
            if not s: return
            self.b_x2c.setEnabled(False)
            self.worker = Worker("xlsx2csv", xlsx_path=p, csv_path=s,
                encoding=self.combo_enc.currentText(), sep=self.combo_sep.currentText().replace("\\t","\t"))
        self._log(f"[信息] 转换开始")
        self.pb.setVisible(True); self.pb.setRange(0,0)
        self.worker.log.connect(self._log)
        self.worker.finished.connect(self._on_cvt)
        self.worker.error.connect(self._on_err)
        self.worker.start()

    def _on_cvt(self, r):
        self.b_c2x.setEnabled(True); self.b_x2c.setEnabled(True); self.pb.setVisible(False)
        QMessageBox.information(self,"成功","转换完成！"); self._log("[完成] 转换完成")


def main():
    import ctypes
    try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except: pass
    app = QApplication(sys.argv)
    w = MainWindow(); w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
