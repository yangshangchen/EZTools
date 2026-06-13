"""
窗口置顶大师 (TopMost Master)
==============================
一键置顶任意窗口 · 窗口列表管理 · 系统托盘 · 全局热键
免费版/专业版 - 通过 IS_PRO 标志切换
"""
import sys, os, json, time, threading, copy
from datetime import datetime, timedelta
import ctypes
from ctypes import wintypes
from PyQt5.QtCore import (QTimer, 
    Qt, QTimer, QThread, pyqtSignal, QPoint, QRect, QSize, QMutex
)
from PyQt5.QtGui import (QCursor, 
    QFont, QIcon, QPixmap, QColor, QPainter, QPen, QPalette, QCursor, QImage
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QCheckBox,
    QSystemTrayIcon, QMenu, QAction, QMessageBox, QSlider,
    QLineEdit, QGroupBox, QGridLayout, QTabWidget, QComboBox,
    QSpinBox, QDialog, QDialogButtonBox, QFormLayout, QInputDialog,
    QSplitter, QFrame, QScrollArea, QToolButton, QAbstractItemView,
    QStyleFactory, QFileDialog, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView
)

# ==================== 版本标志 ====================
IS_PRO = False  # ★ True=专业版, False=免费版
WIN_TITLE = "窗口置顶大师 · 基础版" if IS_PRO else "窗口置顶大师 · 基础版"
EXE_NAME = "TopMost_free.exe" if IS_PRO else "TopMost_free.exe"

# ==================== Win32 常量 ====================
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOMOVE, SWP_NOSIZE = 0x0002, 0x0001
SWP_SHOWWINDOW, SWP_NOACTIVATE = 0x0040, 0x0010
GWL_EXSTYLE, GWL_STYLE = -20, -16
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20
LWA_ALPHA = 0x2

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# === Win32 argtypes (required for 64-bit compatibility) ===
HWND = ctypes.c_void_p
UINT = ctypes.c_uint; BOOL = ctypes.c_bool; LONG = ctypes.c_long; DWORD = ctypes.c_uint
user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, UINT]
user32.SetWindowPos.restype = BOOL
user32.GetWindowLongW.argtypes = [HWND, ctypes.c_int]
user32.GetWindowLongW.restype = LONG
user32.SetWindowLongW.argtypes = [HWND, ctypes.c_int, LONG]
user32.SetWindowLongW.restype = LONG
user32.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.EnumWindows.restype = BOOL
user32.IsWindowVisible.argtypes = [HWND]; user32.IsWindowVisible.restype = BOOL
user32.GetWindowTextW.argtypes = [HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(DWORD)]
user32.GetWindowThreadProcessId.restype = DWORD
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = BOOL
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = HWND
user32.GetForegroundWindow.argtypes = []; user32.GetForegroundWindow.restype = HWND
user32.IsWindow.argtypes = [HWND]; user32.IsWindow.restype = BOOL
user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = BOOL
user32.SetLayeredWindowAttributes.argtypes = [HWND, DWORD, ctypes.c_byte, DWORD]
user32.SetLayeredWindowAttributes.restype = BOOL
kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
kernel32.OpenProcess.restype = HWND
kernel32.CloseHandle.argtypes = [HWND]; kernel32.CloseHandle.restype = BOOL
kernel32.GetModuleBaseNameW.argtypes = [HWND, ctypes.c_void_p, ctypes.c_wchar_p, DWORD]
kernel32.GetModuleBaseNameW.restype = DWORD
# Fix HWND_TOPMOST/HWND_NOTOPMOST to be pointer-sized
old_hwnd_top = "HWND_TOPMOST = -1"
old_hwnd_notop = "HWND_NOTOPMOST = -2"

class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

def enum_windows():
    result = []
    def callback(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd): return True
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        t = title.value.strip()
        if t:
            result.append((hwnd, t, cls.value, pid.value))
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return result

def set_topmost(hwnd, topmost=True):
    h = HWND_TOPMOST if topmost else HWND_NOTOPMOST
    user32.SetWindowPos(hwnd, h, 0, 0, 0, 0, SWP_NOMOVE|SWP_NOSIZE|SWP_SHOWWINDOW)
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if topmost:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | 0x8)
    else:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex & ~0x8)
    user32.SetWindowPos(hwnd, h, 0, 0, 0, 0, SWP_NOMOVE|SWP_NOSIZE|SWP_SHOWWINDOW)

def is_topmost(hwnd):
    return bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0x8)

def get_window_rect(hwnd):
    r = RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    return QRect(r.left, r.top, r.right-r.left, r.bottom-r.top)

def set_window_alpha(hwnd, alpha):
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if alpha < 255:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)
        user32.SetLayeredWindowAttributes(hwnd, 0, max(0,min(255,alpha)), LWA_ALPHA)
    else:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)
        user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)

def set_mouse_through(hwnd, enabled):
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if enabled:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TRANSPARENT)
    else:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex & ~WS_EX_TRANSPARENT)

def get_process_name(pid):
    try:
        h = kernel32.OpenProcess(0x1000|0x400, False, pid)
        if h:
            buf = ctypes.create_unicode_buffer(260)
            kernel32.GetModuleBaseNameW(h, None, buf, 260)
            kernel32.CloseHandle(h)
            return buf.value
    except: pass
    return ""

def get_hwnd_under_cursor():
    pt = wintypes.POINT(); user32.GetCursorPos(ctypes.byref(pt))
    return user32.WindowFromPoint(pt)

# ==================== 主题定义 ====================
THEMES = {
    "light": {
        "bg":"#FFFFFF","fg":"#000000","fg2":"#333333",
        "btn":"#0078D4","btn_fg":"#FFFFFF",
        "border":"#CCCCCC","card":"#F5F5F5","card_hover":"#E8E8E8",
        "success":"#107C10","danger":"#D32F2F","highlight":"#0078D4",
    },
    "dark": {
        "bg":"#1E1E1E","fg":"#FFFFFF","fg2":"#CCCCCC",
        "btn":"#0078D4","btn_fg":"#FFFFFF",
        "border":"#444444","card":"#2D2D2D","card_hover":"#3D3D3D",
        "success":"#4CAF50","danger":"#F44336","highlight":"#4FC3F7",
    },
}
if IS_PRO:
    THEMES["warm_gray"] = {
        "bg":"#F5F0E8","fg":"#2C2C2C","fg2":"#555555",
        "btn":"#C0392B","btn_fg":"#FFFFFF",
        "border":"#D5CEC4","card":"#EDE8DE","card_hover":"#E0D9CE",
        "success":"#27AE60","danger":"#E74C3C","highlight":"#C0392B",
    }

def build_ss(t, font_family="Segoe UI"):
    return f"""
    QMainWindow, QDialog, QWidget#central {{
        background: {t["bg"]}; color: {t["fg"]};
    }}
    QLabel {{
        color: {t["fg"]}; font-family: "{font_family}";
        font-size: 14pt; line-height: 1.5;
    }}
    QPushButton {{
        background: {t["btn"]}; color: {t["btn_fg"]};
        border: none; border-radius: 6px;
        padding: 8px 18px; font-size: 15pt; font-weight: bold;
        font-family: "{font_family}";
    }}
    QPushButton:hover {{ background: {t["highlight"]}; }}
    QPushButton:disabled {{ background: #999; }}
    QLineEdit, QSpinBox, QComboBox, QTextEdit {{
        border: 2px solid {t["border"]};
        border-radius: 6px; padding: 6px 10px;
        font-size: 14pt; color: {t["fg"]};
        background: {t["bg"]}; font-family: "{font_family}";
    }}
    QLineEdit:focus, QSpinBox:focus, QTextEdit:focus {{
        border: 3px solid {t["highlight"]};
    }}
    QListWidget, QTableWidget {{
        border: 2px solid {t["border"]}; border-radius: 6px;
        background: {t["bg"]}; color: {t["fg"]};
        font-size: 13pt; font-family: "{font_family}";
        outline: none;
    }}
    QListWidget::item:selected {{
        background: {t["highlight"]}; color: #FFFFFF;
    }}
    QGroupBox {{
        font-size: 15pt; font-weight: bold; color: {t["fg"]};
        border: 2px solid {t["border"]}; border-radius: 8px;
        margin-top: 16px; padding: 16px 12px 12px;
        font-family: "{font_family}";
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; padding: 0 8px;
        color: {t["highlight"]};
    }}
    QCheckBox {{
        font-size: 14pt; color: {t["fg"]}; spacing: 8px;
        font-family: "{font_family}";
    }}
    QCheckBox::indicator {{
        width: 20px; height: 20px; border: 2px solid {t["border"]};
        border-radius: 4px; background: {t["bg"]};
    }}
    QCheckBox::indicator:checked {{
        background: {t["highlight"]}; border-color: {t["highlight"]};
    }}
    QSlider::groove:horizontal {{
        height: 8px; background: {t["border"]}; border-radius: 4px;
    }}
    QSlider::handle:horizontal {{
        width: 22px; height: 22px; margin: -7px 0;
        background: {t["highlight"]}; border-radius: 11px;
    }}
    QSlider::sub-page:horizontal {{
        background: {t["highlight"]}; border-radius: 4px;
    }}
    QScrollBar:vertical {{
        width: 10px; background: {t["bg"]};
    }}
    QScrollBar::handle:vertical {{
        background: {t["border"]}; border-radius: 5px; min-height: 30px;
    }}
    QTableWidget::item {{ padding: 4px 8px; }}
    QHeaderView::section {{
        background: {t["card"]}; color: {t["fg"]};
        padding: 6px 8px; border: 1px solid {t["border"]};
        font-size: 13pt; font-weight: bold;
    }}
    QProgressBar {{
        border: 2px solid {t["border"]}; border-radius: 6px;
        text-align: center; font-size: 12pt;
        background: {t["bg"]}; color: {t["fg"]};
    }}
    QProgressBar::chunk {{ background: {t["highlight"]}; border-radius: 4px; }}
    """

# ==================== 数据管理 ====================
DATA_DIR = os.path.join(os.path.expanduser("~"), ".topmost_master")
os.makedirs(DATA_DIR, exist_ok=True)
CONF_FILE = os.path.join(DATA_DIR, "config.json")
GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")
BLACKLIST_FILE = os.path.join(DATA_DIR, "blacklist.json")
RULES_FILE = os.path.join(DATA_DIR, "rules.json")
LOG_FILE = os.path.join(DATA_DIR, "log.txt")

def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except: pass
    return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] save err: {e}\n")
        except: pass

def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except: pass

# ==================== 全局热键 ====================
try:
    import keyboard as kb_module
except ImportError:
    kb_module = None

class HotkeyThread(QThread):
    triggered = pyqtSignal()
    def __init__(self, hotkey="ctrl+alt+t", parent=None):
        super().__init__(parent)
        self.hotkey = hotkey
        self._running = True
    def run(self):
        if kb_module is None: return
        try:
            kb_module.add_hotkey(self.hotkey, self._on_hk)
            while self._running:
                time.sleep(0.1)
        except: pass
        finally:
            try: kb_module.remove_hotkey(self.hotkey)
            except: pass
    def _on_hk(self):
        self.triggered.emit()
    def set_hotkey(self, hk):
        self.hotkey = hk
    def stop(self):
        self._running = False
        try: kb_module.remove_hotkey(self.hotkey)
        except: pass

# ==================== 数据类 ====================
class WindowInfo:
    __slots__ = ("hwnd","title","class_name","pid","process",
                 "topmost","alpha","locked","mouse_through","timer_until","group_ids")
    def __init__(self, hwnd, title="", class_name="", pid=0):
        self.hwnd=hwnd; self.title=title; self.class_name=class_name
        self.pid=pid; self.process=get_process_name(pid)
        self.topmost=False; self.alpha=255; self.locked=False
        self.mouse_through=False; self.timer_until=None; self.group_ids=[]

class WindowGroup:
    def __init__(self, name="", hwnds=None):
        self.name=name; self.hwnds=hwnds or []
    def to_dict(self):
        return {"name":self.name,"hwnds":self.hwnds}

class AutoRule:
    def __init__(self, keyword="", match_title=True, match_process=False, enabled=True):
        self.keyword=keyword; self.match_title=match_title
        self.match_process=match_process; self.enabled=enabled
    def to_dict(self):
        return {"keyword":self.keyword,"match_title":self.match_title,
                "match_process":self.match_process,"enabled":self.enabled}

# ==================== 窗口卡片 ====================
class WindowCard(QFrame):
    toggled = pyqtSignal(int, bool)
    alpha_changed = pyqtSignal(int, int)
    lock_toggled = pyqtSignal(int, bool)
    mt_toggled = pyqtSignal(int, bool)
    remove_timer = pyqtSignal(int)

    def __init__(self, winfo, theme, parent=None):
        super().__init__(parent)
        self.winfo=winfo; self.th=theme
        self.setFixedHeight(56 if IS_PRO else 48)
        self.setCursor(Qt.PointingHandCursor)
        self._setup_ui()
        self._refresh_style()

    def _setup_ui(self):
        l = QHBoxLayout(self); l.setContentsMargins(8,4,8,4); l.setSpacing(6)
        self.top_icon = QLabel("📌" if self.winfo.topmost else "○")
        self.top_icon.setFixedWidth(28)
        self.top_icon.setAlignment(Qt.AlignCenter)
        self.top_icon.setStyleSheet(f"font-size:16pt;color:{self.th['highlight']};")
        l.addWidget(self.top_icon)

        v = QVBoxLayout(); v.setSpacing(0)
        self.title_lbl = QLabel(self.winfo.title[:50])
        self.title_lbl.setStyleSheet(f"font-size:13pt;font-weight:bold;color:{self.th['fg']};")
        v.addWidget(self.title_lbl)
        self.proc_lbl = QLabel(self.winfo.process)
        self.proc_lbl.setStyleSheet(f"font-size:11pt;color:{self.th['fg2']};")
        v.addWidget(self.proc_lbl)
        l.addLayout(v, 1)

        if IS_PRO:
            self.alpha_slider = QSlider(Qt.Horizontal)
            self.alpha_slider.setRange(20,100)
            self.alpha_slider.setValue(self.winfo.alpha*100//255)
            self.alpha_slider.setFixedWidth(70)
            self.alpha_slider.setToolTip("透明度")
            self.alpha_slider.valueChanged.connect(lambda v: self._on_a(v))
            l.addWidget(self.alpha_slider)

            self.lock_btn = QToolButton()
            self.lock_btn.setText("🔒" if self.winfo.locked else "🔓")
            self.lock_btn.setCheckable(True)
            self.lock_btn.setChecked(self.winfo.locked)
            self.lock_btn.setFixedSize(30,30)
            self.lock_btn.setToolTip("锁定位置/大小")
            self.lock_btn.clicked.connect(lambda: self.lock_toggled.emit(self.winfo.hwnd, self.lock_btn.isChecked()))
            l.addWidget(self.lock_btn)

            self.mt_btn = QToolButton()
            self.mt_btn.setText("🖱️")
            self.mt_btn.setCheckable(True)
            self.mt_btn.setChecked(self.winfo.mouse_through)
            self.mt_btn.setFixedSize(30,30)
            self.mt_btn.setToolTip("鼠标穿透")
            self.mt_btn.clicked.connect(lambda: self.mt_toggled.emit(self.winfo.hwnd, self.mt_btn.isChecked()))
            l.addWidget(self.mt_btn)

            self.timer_btn = QToolButton()
            self.timer_btn.setText("⏱️")
            self.timer_btn.setFixedSize(30,30)
            self.timer_btn.setToolTip("定时取消")
            self.timer_btn.clicked.connect(lambda: self.remove_timer.emit(self.winfo.hwnd))
            l.addWidget(self.timer_btn)

        self.pin_btn = QPushButton("取消置顶" if self.winfo.topmost else "置顶")
        self.pin_btn.setFixedWidth(80)
        self._style_pin()
        self.pin_btn.clicked.connect(self._toggle)
        l.addWidget(self.pin_btn)

    def _style_pin(self):
        bg = '#107C10' if self.winfo.topmost else self.th['btn']
        self.pin_btn.setStyleSheet(
            "QPushButton{background:" + bg + ";color:white;border:none;border-radius:4px;"
            "padding:4px 8px;font-size:12pt;font-weight:bold;}"
            "QPushButton:hover{opacity:0.85;}"
        )

    def _toggle(self):
        self.winfo.topmost = not self.winfo.topmost
        self.top_icon.setText("📌" if self.winfo.topmost else "○")
        self.pin_btn.setText("取消置顶" if self.winfo.topmost else "置顶")
        self._style_pin()
        self._refresh_style()
        self.toggled.emit(self.winfo.hwnd, self.winfo.topmost)

    def _on_a(self, v):
        a = v*255//100; self.winfo.alpha=a
        self.alpha_changed.emit(self.winfo.hwnd, a)

    def _refresh_style(self):
        bg = self.th["success"] if self.winfo.topmost else self.th["card"]
        self.setStyleSheet(f"WindowCard{{background:{bg};border:2px solid {self.th['border']};border-radius:6px;}}"
                           f"WindowCard:hover{{border-color:{self.th['highlight']};}}")

    def update_theme(self, th):
        self.th=th; self._refresh_style()

    def mouseDoubleClickEvent(self, event):
        self._toggle()
        super().mouseDoubleClickEvent(event)

# ==================== 选择窗口对话框 ====================
class WindowPickerDialog(QDialog):
    """Select window - simple transparent overlay"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("")
        self.setWindowFlags(Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen.width()//2-200, screen.height()//2-60, 400, 120)
        self.selected_hwnd = None
        self._capturing = True
    def paintEvent(self, e):
        if not self._capturing: return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(0,120,212,220))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(10,10,380,100,16,16)
        p.setPen(QPen(QColor("white"),2))
        f = QFont("Segoe UI",18,QFont.Bold)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, chr(0x1F3AF)+" Click target window\nESC cancel")
        p.end()
    def mousePressEvent(self, e):
        if not self._capturing: return
        if e.button() == Qt.LeftButton:
            self._capturing = False
            pos = QCursor.pos()
            self.hide()
            QApplication.processEvents()
            QTimer.singleShot(30, lambda: self._cap(pos))
    def _cap(self, pos):
        pt = wintypes.POINT()
        pt.x = int(pos.x()); pt.y = int(pos.y())
        hwnd = user32.WindowFromPoint(pt)
        if hwnd:
            self.selected_hwnd = hwnd
        self.accept()
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._capturing = False
            self.reject()

class GroupDialog(QDialog):
    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.setWindowTitle("分组管理"); self.setFixedSize(500,400)
        self.groups = groups; self._setup_ui()

    def _setup_ui(self):
        l = QVBoxLayout(self); l.setSpacing(12)
        self.lw = QListWidget(); self._refresh(); l.addWidget(self.lw, 1)
        h = QHBoxLayout()
        for t, fn in [("新建分组",self._add),("删除分组",self._del),("完成",self.accept)]:
            b = QPushButton(t); b.clicked.connect(fn); h.addWidget(b)
        l.addLayout(h)

    def _refresh(self):
        self.lw.clear()
        for g in self.groups:
            it = QListWidgetItem(f"{g.name} ({len(g.hwnds)}个窗口)")
            it.setData(Qt.UserRole, g); self.lw.addItem(it)

    def _add(self):
        name, ok = QInputDialog.getText(self, "新建分组", "分组名称:")
        if ok and name.strip():
            self.groups.append(WindowGroup(name.strip())); self._refresh()

    def _del(self):
        it = self.lw.currentItem()
        if it: self.groups.remove(it.data(Qt.UserRole)); self._refresh()

# ==================== 规则管理 ====================
class RuleDialog(QDialog):
    def __init__(self, rules, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自动置顶规则"); self.setFixedSize(550,400)
        self.rules = rules; self._setup_ui()

    def _setup_ui(self):
        l = QVBoxLayout(self); l.setSpacing(12)
        self.table = QTableWidget(); self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["关键词","匹配标题","匹配进程","启用"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self._refresh(); l.addWidget(self.table, 1)
        h = QHBoxLayout()
        for t, fn in [("添加规则",self._add),("删除规则",self._del),("完成",self.accept)]:
            b = QPushButton(t); b.clicked.connect(fn); h.addWidget(b)
        l.addLayout(h)

    def _refresh(self):
        self.table.setRowCount(len(self.rules))
        for i,r in enumerate(self.rules):
            self.table.setItem(i,0,QTableWidgetItem(r.keyword))
            self.table.setItem(i,1,QTableWidgetItem("✓" if r.match_title else ""))
            self.table.setItem(i,2,QTableWidgetItem("✓" if r.match_process else ""))
            it = QTableWidgetItem(); it.setFlags(it.flags()|Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if r.enabled else Qt.Unchecked)
            self.table.setItem(i,3,it)

    def _add(self):
        kw, ok = QInputDialog.getText(self,"添加规则","关键词:")
        if ok and kw.strip():
            self.rules.append(AutoRule(keyword=kw.strip())); self._refresh()

    def _del(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.rules):
            del self.rules[row]; self._refresh()

# ==================== 设置对话框 ====================
class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置"); self.setFixedSize(450,380)
        self.config=config; self._setup_ui()

    def _setup_ui(self):
        l = QVBoxLayout(self); l.setSpacing(12)
        self.auto_cb = QCheckBox("开机自启")
        self.auto_cb.setChecked(self.config.get("autostart",False))
        l.addWidget(self.auto_cb)
        h = QHBoxLayout(); h.addWidget(QLabel("主题:"))
        self.theme_cb = QComboBox()
        for k in THEMES: self.theme_cb.addItem(k)
        self.theme_cb.setCurrentText(self.config.get("theme","light"))
        h.addWidget(self.theme_cb,1); l.addLayout(h)
        h2 = QHBoxLayout(); h2.addWidget(QLabel("全局热键:"))
        self.hk_edit = QLineEdit(self.config.get("hotkey","ctrl+alt+t"))
        self.hk_edit.setPlaceholderText("如 ctrl+alt+t")
        if not IS_PRO: self.hk_edit.setEnabled(False)
        h2.addWidget(self.hk_edit,1); l.addLayout(h2)
        h3 = QHBoxLayout(); h3.addWidget(QLabel("刷新间隔(秒):"))
        self.ref_spin = QSpinBox(); self.ref_spin.setRange(1,60)
        self.ref_spin.setValue(self.config.get("refresh_interval",3))
        h3.addWidget(self.ref_spin); h3.addStretch(); l.addLayout(h3)
        if IS_PRO:
            g = QGroupBox("云同步 (WebDAV)")
            fl = QFormLayout(g)
            self.wd_url = QLineEdit(self.config.get("webdav_url",""))
            self.wd_url.setPlaceholderText("https://example.com/remote.php/dav/")
            fl.addRow("地址:",self.wd_url)
            self.wd_user = QLineEdit(self.config.get("webdav_user",""))
            fl.addRow("用户名:",self.wd_user)
            self.wd_pass = QLineEdit(self.config.get("webdav_pass",""))
            self.wd_pass.setEchoMode(QLineEdit.Password)
            fl.addRow("密码:",self.wd_pass)
            l.addWidget(g)
        l.addStretch()
        ok_btn = QPushButton("保存")
        ok_btn.clicked.connect(self.accept)
        l.addWidget(ok_btn, alignment=Qt.AlignCenter)

    def get_config(self):
        self.config["autostart"]=self.auto_cb.isChecked()
        self.config["theme"]=self.theme_cb.currentText()
        self.config["hotkey"]=self.hk_edit.text().strip()
        self.config["refresh_interval"]=self.ref_spin.value()
        if IS_PRO:
            self.config["webdav_url"]=self.wd_url.text().strip()
            self.config["webdav_user"]=self.wd_user.text().strip()
            self.config["webdav_pass"]=self.wd_pass.text().strip()
        return self.config

# ==================== 主窗口 ====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WIN_TITLE)
        self.resize(800, 600)
        self.setMinimumSize(600, 400)
        self.config = load_json(CONF_FILE, {
            "autostart":False,"theme":"light","hotkey":"ctrl+alt+t",
            "refresh_interval":3,"webdav_url":"","webdav_user":"","webdav_pass":"",
            "free_upgrade_shown":"",
        })
        self.theme_name = self.config.get("theme","light")
        if self.theme_name not in THEMES: self.theme_name = "light"
        self.th = THEMES[self.theme_name]

        self.groups = []; self.rules = []
        if IS_PRO:
            raw = load_json(GROUPS_FILE, [])
            self.groups = [WindowGroup(**g) for g in raw]
            raw2 = load_json(RULES_FILE, [])
            self.rules = [AutoRule(**r) for r in raw2]
        self.blacklist = load_json(BLACKLIST_FILE, [])

        self.windows = {}; self.cards = {}
        self._running = True; self._lock_rects = {}

        self._setup_ui()
        self._setup_tray()
        self._setup_hotkey()
        self._apply_theme()
        self._refresh_windows()

        interval = self.config.get("refresh_interval",3)*1000
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_windows)
        self._refresh_timer.start(interval)

        if IS_PRO:
            self._rule_timer = QTimer(self)
            self._rule_timer.timeout.connect(self._check_auto_rules)
            self._rule_timer.start(5000)
            self._lock_timer = QTimer(self)
            self._lock_timer.timeout.connect(self._enforce_locks)
            self._lock_timer.start(500)

        self._apply_autostart()
        if not IS_PRO:
            QTimer.singleShot(5000, self._maybe_show_upgrade)

    def _setup_ui(self):
        c = QWidget(); c.setObjectName("central")
        self.setCentralWidget(c)
        ml = QVBoxLayout(c); ml.setSpacing(8); ml.setContentsMargins(10,10,10,10)

        tb = QWidget(); tb.setFixedHeight(50)
        tl = QHBoxLayout(tb); tl.setContentsMargins(0,0,0,0); tl.setSpacing(8)

        self.pick_btn = QPushButton("🎯 选择窗口")
        self.pick_btn.setFixedWidth(140)
        self.pick_btn.clicked.connect(self._pick_window)
        tl.addWidget(self.pick_btn)

        self.unpin_btn = QPushButton("取消全部置顶")
        self.unpin_btn.clicked.connect(self._unpin_all)
        tl.addWidget(self.unpin_btn)

        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self._refresh_windows)
        tl.addWidget(self.refresh_btn)

        tl.addStretch()
        self.always_cb = QCheckBox("总在最前")
        self.always_cb.toggled.connect(self._toggle_top)
        tl.addWidget(self.always_cb)

        self.theme_btn = QPushButton("🎨")
        self.theme_btn.setFixedWidth(44)
        self.theme_btn.clicked.connect(self._cycle_theme)
        tl.addWidget(self.theme_btn)

        self.settings_btn = QPushButton("⚙️")
        self.settings_btn.setFixedWidth(44)
        self.settings_btn.clicked.connect(self._show_settings)
        tl.addWidget(self.settings_btn)

        if IS_PRO:
            for txt, fn in [("📁 分组",self._show_groups),("📋 规则",self._show_rules),("⛔ 黑名单",self._show_blacklist)]:
                b = QPushButton(txt); b.clicked.connect(fn); tl.addWidget(b)

        ml.addWidget(tb)

        self.stats_lbl = QLabel("加载中...")
        self.stats_lbl.setStyleSheet(f"font-size:12pt;color:{self.th['fg2']};padding:4px 0;")
        ml.addWidget(self.stats_lbl)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.list_w = QWidget()
        self.list_l = QVBoxLayout(self.list_w)
        self.list_l.setSpacing(4); self.list_l.setContentsMargins(0,0,0,0)
        self.list_l.addStretch()
        self.scroll.setWidget(self.list_w)
        ml.addWidget(self.scroll, 1)

        self.status_lbl = QLabel("就绪")
        self.status_lbl.setStyleSheet(f"font-size:12pt;color:{self.th['fg2']};padding:2px 0;")
        ml.addWidget(self.status_lbl)

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        pix = QPixmap(32,32); pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setBrush(QColor(self.th["highlight"])); p.setPen(Qt.NoPen)
        p.drawRoundedRect(2,2,28,28,6,6)
        p.setPen(QPen(QColor("white"),2)); p.drawText(pix.rect(),Qt.AlignCenter,"T")
        p.end()
        self.tray.setIcon(QIcon(pix))
        self.tray.setToolTip(WIN_TITLE)
        m = QMenu()
        m.addAction("显示主窗口").triggered.connect(self.show_normal)
        if IS_PRO:
            m.addAction("分组管理").triggered.connect(self._show_groups)
        m.addAction("置顶列表").triggered.connect(self._show_topmost)
        m.addSeparator()
        m.addAction("退出").triggered.connect(self.quit_app)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.show_normal() if r==QSystemTrayIcon.DoubleClick else None)
        self.tray.show()

    def show_normal(self):
        self.showNormal(); self.activateWindow(); self.raise_(); self._refresh_windows()

    def _setup_hotkey(self):
        hk = self.config.get("hotkey","ctrl+alt+t")
        self.hotkey_th = HotkeyThread(hk, self)
        self.hotkey_th.triggered.connect(self._on_hotkey)
        self.hotkey_th.start()

    def _on_hotkey(self):
        try:
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                set_topmost(hwnd, not is_topmost(hwnd))
                self._refresh_windows()
                self.status_lbl.setText("热键触发 ✓")
        except Exception as e: log(f"hotkey err: {e}")

    def _toggle_top(self, chk):
        f = self.windowFlags()
        self.setWindowFlags(f | Qt.WindowStaysOnTopHint if chk else f & ~Qt.WindowStaysOnTopHint)
        self.show()

    def _cycle_theme(self):
        keys = list(THEMES.keys())
        idx = keys.index(self.theme_name)
        self.theme_name = keys[(idx+1)%len(keys)]
        self.config["theme"]=self.theme_name; save_json(CONF_FILE,self.config)
        self.th = THEMES[self.theme_name]; self._apply_theme(); self._refresh_windows()

    def _apply_theme(self):
        self.setStyleSheet(build_ss(self.th))
        for c in self.cards.values(): c.update_theme(self.th)
        self.stats_lbl.setStyleSheet(f"font-size:12pt;color:{self.th['fg2']};padding:4px 0;")
        self.status_lbl.setStyleSheet(f"font-size:12pt;color:{self.th['fg2']};padding:2px 0;")
        pix = QPixmap(32,32); pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setBrush(QColor(self.th["highlight"])); p.setPen(Qt.NoPen)
        p.drawRoundedRect(2,2,28,28,6,6)
        p.setPen(QPen(QColor("white"),2)); p.drawText(pix.rect(),Qt.AlignCenter,"T")
        p.end(); self.tray.setIcon(QIcon(pix))

    def _apply_autostart(self):
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE|winreg.KEY_QUERY_VALUE)
            if self.config.get("autostart",False):
                exe = sys.executable if getattr(sys,'frozen',False) else sys.argv[0]
                winreg.SetValueEx(k,"TopMostMaster",0,winreg.REG_SZ,f'"{exe}"')
            else:
                try: winreg.DeleteValue(k,"TopMostMaster")
                except: pass
            winreg.CloseKey(k)
        except Exception as e: log(f"autostart: {e}")

    def _pick_window(self):
        self.status_lbl.setText("🎯 点击目标窗口...")
        QApplication.processEvents()
        d = WindowPickerDialog(self)
        if d.exec_() == QDialog.Accepted and d.selected_hwnd:
            hwnd = d.selected_hwnd
            set_topmost(hwnd, True)
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            t = buf.value.strip()[:30]
            self.status_lbl.setText("✅ " + t + " 已置顶")
        else:
            self.status_lbl.setText("已取消")
        self._refresh_windows()

    def _unpin_all(self):
        for w in self.windows.values():
            if w.topmost: set_topmost(w.hwnd, False)
        self._refresh_windows(); self.status_lbl.setText("已取消全部置顶")

    def _refresh_windows(self):
        try:
            raw = enum_windows()
            cur = set()
            for hwnd,title,cls,pid in raw:
                cur.add(hwnd)
                if hwnd in self.windows:
                    self.windows[hwnd].title=title
                    self.windows[hwnd].topmost=is_topmost(hwnd)
                else:
                    wi = WindowInfo(hwnd,title,cls,pid)
                    wi.topmost=is_topmost(hwnd)
                    self.windows[hwnd]=wi
            for hwnd in list(self.windows.keys()):
                if hwnd not in cur: del self.windows[hwnd]
            self._rebuild_cards()
            self._update_stats()
        except Exception as e: log(f"refresh: {e}")

    def _rebuild_cards(self):
        for c in self.cards.values():
            self.list_l.removeWidget(c); c.deleteLater()
        self.cards.clear()
        sw = sorted(self.windows.values(), key=lambda w:(0 if w.topmost else 1,w.title.lower()))
        sw = [w for w in sw if w.process.lower() not in [b.lower() for b in self.blacklist]]
        for wi in sw:
            card = WindowCard(wi, self.th)
            card.toggled.connect(self._on_toggle)
            if IS_PRO:
                card.alpha_changed.connect(self._on_alpha)
                card.lock_toggled.connect(self._on_lock)
                card.mt_toggled.connect(self._on_mt)
                card.remove_timer.connect(self._on_timer)
            self.list_l.insertWidget(self.list_l.count()-1, card)
            self.cards[wi.hwnd]=card

    def _update_stats(self):
        t = len(self.windows); p = sum(1 for w in self.windows.values() if w.topmost)
        b = len(self.blacklist)
        self.stats_lbl.setText(f"🪟 共 {t} 个窗口 | 📌 已置顶 {p} 个"+(f" | ⛔ 黑名单 {b}" if b else ""))

    def _on_toggle(self, hwnd, top):
        set_topmost(hwnd, top)
        self.status_lbl.setText("✅ 已置顶" if top else "已取消")
        self._update_stats()

    def _on_alpha(self, hwnd, a): set_window_alpha(hwnd, a)

    def _on_lock(self, hwnd, locked):
        if locked: self._lock_rects[hwnd]=get_window_rect(hwnd)
        else: self._lock_rects.pop(hwnd,None)

    def _on_mt(self, hwnd, en): set_mouse_through(hwnd, en)

    def _on_timer(self, hwnd):
        m, ok = QInputDialog.getInt(self,"定时取消","分钟后取消:",10,1,999)
        if ok and hwnd in self.windows:
            self.windows[hwnd].timer_until = datetime.now()+timedelta(minutes=m)
            self.status_lbl.setText(f"⏱️ {m}分钟后取消"); self._refresh_windows()

    def _enforce_locks(self):
        try:
            for hwnd,rect in list(self._lock_rects.items()):
                if user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd):
                    cur = get_window_rect(hwnd)
                    if cur!=rect:
                        user32.SetWindowPos(hwnd,0,rect.x(),rect.y(),rect.width(),rect.height(),
                                            SWP_NOACTIVATE|SWP_SHOWWINDOW)
        except: pass

    def _check_auto_rules(self):
        if not IS_PRO or not self.rules: return
        try:
            for rule in self.rules:
                if not rule.enabled or not rule.keyword: continue
                kw = rule.keyword.lower()
                for hwnd,wi in self.windows.items():
                    if wi.topmost: continue
                    if (rule.match_title and kw in wi.title.lower()) or \
                       (rule.match_process and kw in wi.process.lower()):
                        set_topmost(hwnd, True); wi.topmost=True
                        self.status_lbl.setText(f"🤖 自动置顶: {wi.title[:30]}")
            self._rebuild_cards(); self._update_stats()
        except Exception as e: log(f"auto rule: {e}")

    def _show_settings(self):
        d = SettingsDialog(self.config, self)
        if d.exec_()==QDialog.Accepted:
            self.config=d.get_config(); save_json(CONF_FILE,self.config)
            self._apply_autostart()
            self.hotkey_th.set_hotkey(self.config.get("hotkey","ctrl+alt+t"))
            self.th=THEMES[self.config.get("theme","light")]; self._apply_theme()
            self._refresh_windows(); self.status_lbl.setText("设置已保存")

    def _show_groups(self):
        if not IS_PRO: return
        d = GroupDialog(self.groups, self)
        if d.exec_()==QDialog.Accepted:
            save_json(GROUPS_FILE,[g.to_dict() for g in self.groups])

    def _show_rules(self):
        if not IS_PRO: return
        d = RuleDialog(self.rules, self)
        if d.exec_()==QDialog.Accepted:
            save_json(RULES_FILE,[r.to_dict() for r in self.rules])

    # More careful blacklist dialog
    def _show_blacklist(self):
        d = QDialog(self); d.setWindowTitle("黑名单管理"); d.setFixedSize(400,300)
        l = QVBoxLayout(d); l.setSpacing(8)
        l.addWidget(QLabel("以下进程不会被显示在列表中:"))
        lw = QListWidget()
        for p in self.blacklist: lw.addItem(p)
        l.addWidget(lw,1)
        h = QHBoxLayout()
        ab = QPushButton("添加"); db = QPushButton("删除选中")
        def add_b():
            n,ok=QInputDialog.getText(d,"添加","进程名 (如 notepad.exe):")
            if ok and n.strip() and n.strip() not in self.blacklist:
                self.blacklist.append(n.strip()); lw.addItem(n.strip())
                save_json(BLACKLIST_FILE,self.blacklist); self._refresh_windows()
        def del_b():
            it=lw.currentItem()
            if it: self.blacklist.remove(it.text()); lw.takeItem(lw.row(it))
            save_json(BLACKLIST_FILE,self.blacklist); self._refresh_windows()
        ab.clicked.connect(add_b); db.clicked.connect(del_b)
        h.addWidget(ab); h.addWidget(db); l.addLayout(h)
        cb = QPushButton("完成"); cb.clicked.connect(d.accept)
        l.addWidget(cb, alignment=Qt.AlignCenter)
        d.exec_()

    def _show_topmost(self):
        top = [w for w in self.windows.values() if w.topmost]
        if not top: QMessageBox.information(self,"置顶列表","当前没有已置顶的窗口"); return
        msg = "📌 已置顶窗口:\n\n"
        for w in top[:20]: msg += f"  • {w.title[:40]} ({w.process})\n"
        if len(top)>20: msg += f"  ... 还有{len(top)-20}个\n"
        QMessageBox.information(self,f"置顶列表 ({len(top)})",msg)

    def _maybe_show_upgrade(self):
        if IS_PRO: return
        today = datetime.now().strftime("%Y-%m-%d")
        if self.config.get("free_upgrade_shown")!=today:
            self.config["free_upgrade_shown"]=today; save_json(CONF_FILE,self.config)
            QMessageBox.information(self,"升级专业版",
                "🌟 窗口置顶大师 · 基础版\n\n专业版功能:\n"
                "• 窗口分组管理\n• 透明度调节\n• 位置/大小锁定\n"
                "• 鼠标穿透模式\n• 定时取消置顶\n• 自动规则置顶\n"
                "• 自定义热键\n• 黑名单管理\n• 云端同步\n\n"
                "获取方式: 联系开发者")

    def quit_app(self):
        self._running=False; self.hotkey_th.stop(); self.hotkey_th.wait(1000)
        self.tray.hide(); QApplication.instance().quit()

    def closeEvent(self, event):
        event.ignore(); self.hide()
        self.tray.showMessage("窗口置顶大师","程序已最小化到系统托盘",QSystemTrayIcon.Information,2000)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w=self.scroll.viewport().width()-20
        for c in self.cards.values(): c.setMinimumWidth(w)

# ==================== 入口 ====================
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    f = QFont("Segoe UI", 14); f.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(f)
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except:
        try: ctypes.windll.user32.SetProcessDPIAware()
        except: pass
    w = MainWindow(); w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
