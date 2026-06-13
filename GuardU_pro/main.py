# -*- coding: utf-8 -*-
"""守着你 (GuardU) - 安心版"""
import sys, os, json, smtplib, ssl, subprocess, requests
from cryptography.fernet import Fernet
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QCheckBox, QComboBox,
    QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QProgressBar, QGroupBox,
    QTextEdit, QMenu, QSplitter, QFrame, QSystemTrayIcon, QTabWidget,
    QFormLayout, QSpinBox, QTimeEdit, QDialog, QDialogButtonBox,
    QCalendarWidget)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, QDate, QTime
from PyQt5.QtGui import QFont, QIcon, QColor, QBrush, QTextCursor, QPixmap, QPainter, QPalette

DATA_DIR = os.path.join(os.path.expanduser("~"), ".guardu_pro")
os.makedirs(DATA_DIR, exist_ok=True)
CHECKIN_FILE = os.path.join(DATA_DIR, "checkin.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
SEND_COUNT_FILE = os.path.join(DATA_DIR, "send_count.json")
REG_KEY = r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "GuardU_Pro"


def _load_json(path, default=None):
    if default is None:
        default = {}
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except:
        pass
    return default


def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except:
        pass


def get_consecutive_days(dates_list):
    if not dates_list:
        return 0
    sorted_dates = sorted(set(dates_list), reverse=True)
    today = date.today()
    if sorted_dates[0] != today.isoformat():
        return 0
    count = 1
    for i in range(len(sorted_dates) - 1):
        d1 = date.fromisoformat(sorted_dates[i])
        d2 = date.fromisoformat(sorted_dates[i + 1])
        diff = (d1 - d2).days
        if diff == 1:
            count += 1
        else:
            break
    return count


def generate_tray_icon():
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#0078D4"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(2, 2, 28, 28)
    painter.setPen(QColor("#FFFFFF"))
    font = QFont("Segoe UI", 16, QFont.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "G")
    painter.end()
    return QIcon(pixmap)


class MailWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, smtp_server, smtp_port, sender, password, receiver, subject, body):
        super().__init__()
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender = sender
        self.password = password
        self.receiver = receiver
        self.subject = subject
        self.body = body

    def run(self):
        try:
            msg = MIMEMultipart()
            msg["From"] = self.sender
            msg["To"] = self.receiver
            msg["Subject"] = self.subject
            msg.attach(MIMEText(self.body, "plain", "utf-8"))
            ctx = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10) as server:
                server.starttls(context=ctx)
                server.login(self.sender, self.password)
                server.send_message(msg)
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


class AlertWindow(QMainWindow):
    def __init__(self, on_safe, on_help=None):
        super().__init__()
        self.on_safe = on_safe
        self.on_help = on_help
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet("background:#FFF;")
        cw = QWidget(); self.setCentralWidget(cw)
        ml = QVBoxLayout(cw); ml.setAlignment(Qt.AlignCenter)
        ml.setSpacing(16); ml.setContentsMargins(30,30,30,30)
        lbl = QLabel("⚠️ 您已超过48小时未签到！")
        lbl.setStyleSheet("font-size:20pt;font-weight:bold;color:#D40000;")
        lbl.setAlignment(Qt.AlignCenter)
        ml.addWidget(lbl)
        lbl2 = QLabel("为确保您的安全，请确认您一切平安")
        lbl2.setStyleSheet("font-size:16pt;color:#333;")
        lbl2.setAlignment(Qt.AlignCenter)
        ml.addWidget(lbl2)
        btn_safe = QPushButton("✅ 我没事")
        btn_safe.setMinimumHeight(44)
        btn_safe.setStyleSheet("background:#0078D4;color:#FFF;font-size:16pt;font-weight:bold;border:none;border-radius:6px;padding:10px 30px;")
        btn_safe.clicked.connect(self._safe)
        ml.addWidget(btn_safe)
        if on_help:
            btn_help = QPushButton("🆘 发送求助")
            btn_help.setMinimumHeight(44)
            btn_help.setStyleSheet("background:#D40000;color:#FFF;font-size:16pt;font-weight:bold;border:none;border-radius:6px;padding:10px 30px;")
            btn_help.clicked.connect(self._help)
            ml.addWidget(btn_help)
        self.resize(420, 280)
        self.center()

    def center(self):
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width()-self.width())//2, (screen.height()-self.height())//2)

    def closeEvent(self, e):
        e.ignore()

    def _safe(self):
        if self.on_safe:
            self.on_safe()
        self.close()

    def _help(self):
        if self.on_help:
            self.on_help()


class ProWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.checkin_data = _load_json(CHECKIN_FILE, {"dates": [], "last_checkin": ""})
        self.settings = _load_json(SETTINGS_FILE)
        self.send_count = _load_json(SEND_COUNT_FILE, {"date": "", "count": 0})
        self.alert_windows = []
        self.init_ui()
        self.init_tray()
        self.init_timers()
        self._update_checkin_display()
        self._apply_auto_start()

    def init_ui(self):
        self.setWindowTitle("守着你 · 守护版")
        self.resize(1000, 700)
        self.setMinimumSize(800, 500)
        font = QFont("Segoe UI", 14)
        self.setFont(font)
        cw = QWidget(); self.setCentralWidget(cw)
        ml = QVBoxLayout(cw); ml.setSpacing(8); ml.setContentsMargins(12,12,12,12)

        # Top bar
        tb = QHBoxLayout(); tb.setSpacing(8)
        title = QLabel("守着你 · 守护版")
        title.setStyleSheet("font-size:22pt;font-weight:bold;color:#0078D4;")
        tb.addWidget(title)
        tb.addStretch()
        self.chk_top = QCheckBox("总在最前")
        self.chk_top.setChecked(True)
        self.chk_top.stateChanged.connect(self._top)
        tb.addWidget(self.chk_top)
        ml.addLayout(tb)

        # Tabs
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane{border:2px solid #DDD;border-radius:6px;background:#FFF;}"
                          "QTabBar::tab{font-size:14pt;padding:8px 20px;color:#333;background:#F5F5F5;border:1px solid #DDD;border-bottom:none;border-top-left-radius:6px;border-top-right-radius:6px;}"
                          "QTabBar::tab:selected{color:#000;background:#FFF;font-weight:bold;}")
        tabs.addTab(self._build_checkin_tab(), "我平安 🌟")
        tabs.addTab(self._build_contacts_tab(), "联系人")
        tabs.addTab(self._build_calendar_tab(), "签到日历")
        tabs.addTab(self._build_report_tab(), "月度报告")
        tabs.addTab(self._build_settings_tab(), "设置")
        ml.addWidget(tabs, 1)

        # Status bar
        self.lbl_status = QLabel("已安全运行")
        self.lbl_status.setStyleSheet("font-size:12pt;color:#666;padding:4px 0;")
        ml.addWidget(self.lbl_status)

        self.setStyleSheet("QMainWindow{background:#FFF;}QWidget{background:#FFF;color:#000;}"
                          "QLineEdit{border:2px solid #CCC;border-radius:6px;padding:8px 12px;font-size:14pt;color:#000;background:#FFF;}"
                          "QLineEdit:focus{border:3px solid #0078D4;}"
                          "QPushButton{border-radius:6px;font-size:14pt;padding:8px 16px;}")

    def _build_checkin_tab(self):
        w = QWidget()
        l = QVBoxLayout(w); l.setAlignment(Qt.AlignCenter)
        l.setSpacing(20)

        self.lbl_greeting = QLabel("👋 今天也要平安哦~")
        self.lbl_greeting.setStyleSheet("font-size:24pt;font-weight:bold;color:#000;")
        self.lbl_greeting.setAlignment(Qt.AlignCenter)
        l.addWidget(self.lbl_greeting)

        self.lbl_checkin_status = QLabel("")
        self.lbl_checkin_status.setStyleSheet("font-size:18pt;color:#333;")
        self.lbl_checkin_status.setAlignment(Qt.AlignCenter)
        l.addWidget(self.lbl_checkin_status)

        self.lbl_streak = QLabel("")
        self.lbl_streak.setStyleSheet("font-size:16pt;color:#0078D4;")
        self.lbl_streak.setAlignment(Qt.AlignCenter)
        l.addWidget(self.lbl_streak)

        self.btn_checkin = QPushButton("🌟 我平安")
        self.btn_checkin.setMinimumSize(200, 60)
        self.btn_checkin.setStyleSheet("background:#0078D4;color:#FFF;font-size:20pt;font-weight:bold;border:none;border-radius:12px;padding:12px 30px;")
        self.btn_checkin.clicked.connect(self._do_checkin)
        l.addWidget(self.btn_checkin, 0, Qt.AlignCenter)

        # Last checkin info
        self.lbl_last = QLabel("")
        self.lbl_last.setStyleSheet("font-size:14pt;color:#666;")
        self.lbl_last.setAlignment(Qt.AlignCenter)
        l.addWidget(self.lbl_last)

        l.addStretch()
        return w

    def _build_settings_tab(self):
        w = QWidget()
        l = QVBoxLayout(w); l.setSpacing(12)

        # Auto-start
        gb1 = QGroupBox("开机自启")
        gb1.setStyleSheet("QGroupBox{font-size:16pt;font-weight:bold;color:#000;border:2px solid #DDD;border-radius:6px;margin-top:14px;padding:12px;}"
                          "QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 6px;}")
        gb1l = QVBoxLayout(gb1)
        self.chk_autostart = QCheckBox("开机自动启动守着你")
        self.chk_autostart.setStyleSheet("font-size:14pt;color:#000;")
        self.chk_autostart.stateChanged.connect(self._toggle_autostart)
        gb1l.addWidget(self.chk_autostart)
        l.addWidget(gb1)

        # Email settings
        gb2 = QGroupBox("紧急联系 (邮件)")
        gb2.setStyleSheet(gb1.styleSheet())
        fl = QFormLayout(gb2); fl.setSpacing(8)
        fl.setLabelAlignment(Qt.AlignRight)
        h_smtp = QHBoxLayout()
        self.edit_smtp = QLineEdit(); self.edit_smtp.setPlaceholderText("smtp.example.com")
        h_smtp.addWidget(self.edit_smtp, 1)
        self.combo_preset = QComboBox()
        self.combo_preset.addItems(["快速选择...","QQ邮箱","163邮箱","Gmail","Outlook","126邮箱","新浪邮箱"])
        self.combo_preset.currentIndexChanged.connect(self._apply_preset)
        self.combo_preset.setMinimumWidth(130)
        self.combo_preset.setStyleSheet("font-size:14pt;border:2px solid #CCC;border-radius:6px;padding:4px;")
        h_smtp.addWidget(self.combo_preset)
        fl.addRow("SMTP服务器:", h_smtp)
        self.edit_port = QSpinBox(); self.edit_port.setRange(1, 65535); self.edit_port.setValue(587)
        self.edit_port.setMinimumHeight(38)
        fl.addRow("端口:", self.edit_port)
        self.edit_email = QLineEdit(); self.edit_email.setPlaceholderText("your@email.com")
        fl.addRow("邮箱账号:", self.edit_email)
        self.edit_pwd = QLineEdit(); self.edit_pwd.setEchoMode(QLineEdit.Password)
        self.edit_pwd.setPlaceholderText("密码或授权码")
        fl.addRow("密码:", self.edit_pwd)
        self.edit_target = QLineEdit(); self.edit_target.setPlaceholderText("target@email.com")
        fl.addRow("目标邮箱:", self.edit_target)
        btn_save = QPushButton("保存设置")
        btn_save.setStyleSheet("background:#0078D4;color:#FFF;font-weight:bold;border:none;border-radius:6px;padding:8px 20px;font-size:14pt;")
        btn_save.clicked.connect(self._save_settings)
        fl.addRow("", btn_save)
        self.lbl_send_status = QLabel("")
        self.lbl_send_status.setStyleSheet("font-size:12pt;color:#666;")
        fl.addRow("", self.lbl_send_status)
        l.addWidget(gb2)

        self._load_settings_to_ui()
        l.addStretch()
        return w

    def init_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(generate_tray_icon())
        self.tray.setToolTip("守着你 · 守护版")
        menu = QMenu()
        act_show = menu.addAction("显示主窗口")
        act_show.triggered.connect(self.show_normal)
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_normal()

    def show_normal(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def init_timers(self):
        # Safety check every hour
        self.safety_timer = QTimer(self)
        self.safety_timer.timeout.connect(self._safety_check)
        self.safety_timer.start(3600000)
        # Pro: smart comfort every 30min
        self.comfort_timer = QTimer(self)
        self.comfort_timer.timeout.connect(self._smart_comfort)
        self.comfort_timer.start(1800000)

    def _top(self, s):
        f = self.windowFlags()
        self.setWindowFlags(f | Qt.WindowStaysOnTopHint if s == Qt.Checked else f & ~Qt.WindowStaysOnTopHint)
        self.show()

    def _log(self, msg):
        if hasattr(self, "lbl_status"):
            self.lbl_status.setText(msg)

    def _do_checkin(self):
        today = date.today().isoformat()
        dates = self.checkin_data.get("dates", [])
        if today not in dates:
            dates.append(today)
        self.checkin_data["dates"] = dates
        self.checkin_data["last_checkin"] = today
        _save_json(CHECKIN_FILE, self.checkin_data)
        self._update_checkin_display()
        self._log("✔️ " + today + " 已签到")

    def _update_checkin_display(self):
        dates = self.checkin_data.get("dates", [])
        last = self.checkin_data.get("last_checkin", "")
        streak = get_consecutive_days(dates)
        today = date.today().isoformat()
        if today in dates:
            self.btn_checkin.setEnabled(False)
            self.btn_checkin.setText("✅ 今天已签到")
            self.lbl_checkin_status.setText("✅ 今天已报平安，很棒！")
        else:
            self.btn_checkin.setEnabled(True)
            self.btn_checkin.setText("🌟 我平安")
            self.lbl_checkin_status.setText("诰？今天还没签到呢~")
        self.lbl_streak.setText("🔥 已连续签到 " + str(streak) + " 天")
        self.lbl_last.setText("上次签到：" + (last if last else "暂无"))

    def _save_settings(self):
        self.settings = {
            "smtp_server": self.edit_smtp.text().strip(),
            "smtp_port": self.edit_port.value(),
            "email": self.edit_email.text().strip(),
            "password": self.edit_pwd.text(),
            "target_email": self.edit_target.text().strip(),
        }
        _save_json(SETTINGS_FILE, self.settings)
        QMessageBox.information(self, "保存成功", "设置已保存")

    def _load_settings_to_ui(self):
        if self.settings:
            self.edit_smtp.setText(self.settings.get("smtp_server", ""))
            self.edit_port.setValue(self.settings.get("smtp_port", 587))
            self.edit_email.setText(self.settings.get("email", ""))
            self.edit_pwd.setText(self.settings.get("password", ""))
            self.edit_target.setText(self.settings.get("target_email", ""))

    def _apply_preset(self, idx):
        if idx < 0:
            return
        txt = self.combo_preset.currentText()
        presets = {
            "QQ邮箱": ("smtp.qq.com", 587),
            "163邮箱": ("smtp.163.com", 587),
            "Gmail": ("smtp.gmail.com", 587),
            "Outlook": ("smtp.office365.com", 587),
            "126邮箱": ("smtp.126.com", 587),
            "新浪邮箱": ("smtp.sina.com", 587),
        }
        if txt in presets:
            server, port = presets[txt]
            self.edit_smtp.setText(server)
            self.edit_port.setValue(port)
            if txt == "QQ邮箱":
                self.edit_email.setPlaceholderText("your@qq.com")
        self.combo_preset.setCurrentIndex(0)

    def _toggle_autostart(self, state):
        self._apply_auto_start(state == Qt.Checked)

    def _apply_auto_start(self, force_enable=None):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
            exe_path = sys.argv[0] if getattr(sys, "frozen", False) else sys.executable
            if force_enable is None:
                force_enable = self.chk_autostart.isChecked()
            if force_enable:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            self._log("开机自启设置失败: " + str(e))

    def _safety_check(self):
        last = self.checkin_data.get("last_checkin", "")
        if not last:
            return
        try:
            last_date = date.fromisoformat(last)
            days = (date.today() - last_date).days
            if days >= 2:
                self._show_alert()
        except:
            pass

    def _show_alert(self):
        def on_safe():
            self._do_checkin()
        def on_help():
            self._send_alert_email()
        w = AlertWindow(on_safe, on_help)
        self.alert_windows.append(w)
        w.show()

    def _send_alert_email(self):
        s = self.settings
        if not s.get("smtp_server") or not s.get("email") or not s.get("target_email"):
            QMessageBox.warning(self, "提示", "请先在设置中配置邮箱信息")
            return
        today = date.today().isoformat()
        sc = self.send_count
        # Pro: no daily limit
        body = "【守着你 · 守护版】紧急求助！\n\n用户已超过48小时未签到，可能存在危险。\n请尽快联系确认安全。\n\n-- 来自守着你安全助手"
        self.worker = MailWorker(
            s["smtp_server"], s["smtp_port"],
            s["email"], s["password"],
            s["target_email"],
            "【守着你】紧急求助 - 用户可能处于危险中",
            body
        )
        def on_done(ok, err):
            if ok:
                sc["date"] = today
                sc["count"] = sc.get("count", 0) + 1
                _save_json(SEND_COUNT_FILE, sc)
                self.lbl_send_status.setText("\u2705 求助邮件已发送 (" + str(sc["count"]) + "/1)")
                QMessageBox.information(self, "发送成功", "求助邮件已发送")
            else:
                QMessageBox.critical(self, "发送失败", err)
        self.worker.finished.connect(on_done)
        self.worker.start()

    def _smart_comfort(self):
        now = QTime.currentTime()
        if now.hour() >= 23 or now.hour() < 5:
            if not self.isMinimized():
                tip = QWidget(None, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
                tip.setAttribute(Qt.WA_TranslucentBackground)
                tip.setStyleSheet("background:transparent;")
                tip.resize(360, 140)
                screen = QApplication.primaryScreen().geometry()
                tip.move((screen.width()-360)//2, (screen.height()-140)//2)
                lbl = QLabel(tip)
                lbl.setText("\ud83c\udf19 \u665a\u5b89\uff0c\u522b\u6015\uff0c\u6211\u5728\u5462")
                lbl.setStyleSheet("background:rgba(0,120,212,200);color:#FFF;font-size:18pt;font-weight:bold;border-radius:20px;padding:30px;")
                lbl.setAlignment(Qt.AlignCenter)
                lbl.setGeometry(0, 0, 360, 100)
                btn_close = QPushButton("\u2716", tip)
                btn_close.setGeometry(320, 8, 32, 32)
                btn_close.setStyleSheet("background:transparent;color:#FFF;font-size:16pt;border:none;")
                btn_close.clicked.connect(tip.close)
                tip.show()
                QTimer.singleShot(10000, tip.close)

    def _notify_all_channels(self):
        self._send_alert_email()
        try:
            p = os.path.join(DATA_DIR, "contacts.enc")
            if os.path.exists(p):
                key = self._get_fernet_key()
                with open(p, "rb") as f:
                    ct = json.loads(Fernet(key).decrypt(f.read()).decode())
                for c in ct:
                    if "@" not in c and len(c) > 10:
                        try:
                            requests.get(c, timeout=5)
                        except:
                            pass
        except:
            pass

    def quit_app(self):
        self.tray.hide()
        QApplication.quit()


    def _build_contacts_tab(self):
        w = QWidget()
        l = QVBoxLayout(w); l.setSpacing(12)
        gb = QGroupBox("紧急联系人 (最多5人)")
        gb.setStyleSheet("QGroupBox{font-size:16pt;font-weight:bold;color:#000;border:2px solid #DDD;border-radius:6px;margin-top:14px;padding:12px;}QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 6px;}")
        fl = QFormLayout(gb); fl.setSpacing(8)
        self.contact_edits = []
        for i in range(5):
            e = QLineEdit()
            e.setPlaceholderText("联系人 " + str(i+1) + " 邮箱/手机/服务器Key")
            e.setMinimumHeight(38)
            fl.addRow("联系人" + str(i+1) + ":", e)
            self.contact_edits.append(e)
        l.addWidget(gb)
        btn_s = QPushButton("加密保存联系人")
        btn_s.setMinimumHeight(40)
        btn_s.setStyleSheet("background:#0078D4;color:#FFF;font-weight:bold;border:none;border-radius:6px;font-size:14pt;padding:8px 20px;")
        btn_s.clicked.connect(self._save_contacts)
        l.addWidget(btn_s)
        self._load_contacts()
        l.addStretch()
        return w

    def _get_fernet_key(self):
        kf = os.path.join(DATA_DIR, "key.bin")
        if os.path.exists(kf):
            with open(kf, "rb") as f:
                return f.read()
        k = Fernet.generate_key()
        with open(kf, "wb") as f:
            f.write(k)
        return k

    def _save_contacts(self):
        try:
            ct = [e.text().strip() for e in self.contact_edits if e.text().strip()]
            if not ct:
                QMessageBox.warning(self, "提示", "请输入联系人")
                return
            key = self._get_fernet_key()
            enc = Fernet(key).encrypt(json.dumps(ct).encode())
            with open(os.path.join(DATA_DIR, "contacts.enc"), "wb") as f:
                f.write(enc)
            QMessageBox.information(self, "成功", "联系人已加密保存")
        except Exception as e:
            QMessageBox.critical(self, "错误", "保存失败: " + str(e))

    def _load_contacts(self):
        try:
            p = os.path.join(DATA_DIR, "contacts.enc")
            if not os.path.exists(p):
                return
            key = self._get_fernet_key()
            with open(p, "rb") as f:
                dec = Fernet(key).decrypt(f.read())
            ct = json.loads(dec.decode())
            for i, c in enumerate(ct):
                if i < len(self.contact_edits):
                    self.contact_edits[i].setText(c)
        except:
            pass

    def _build_calendar_tab(self):
        w = QWidget()
        l = QVBoxLayout(w); l.setSpacing(12)
        cal = QCalendarWidget()
        cal.setStyleSheet("QCalendarWidget{font-size:14pt;border:2px solid #DDD;border-radius:6px;}")
        cal.setGridVisible(True)
        dates = self.checkin_data.get("dates", [])
        for ds in dates:
            try:
                dt = QDate.fromString(ds, "yyyy-MM-dd")
                from PyQt5.QtGui import QTextCharFormat
                tf = QTextCharFormat()
                tf.setBackground(QColor("#C8E6C9"))
                tf.setForeground(QColor("#000000"))
                cal.setDateTextFormat(dt, tf)
            except:
                pass
        l.addWidget(cal, 1)
        return w

    def _build_report_tab(self):
        w = QWidget()
        l = QVBoxLayout(w); l.setSpacing(16); l.setAlignment(Qt.AlignCenter)
        lbl = QLabel("导出月度签到报告 (TXT)")
        lbl.setStyleSheet("font-size:18pt;font-weight:bold;color:#000;")
        l.addWidget(lbl, 0, Qt.AlignCenter)
        self.combo_month = QComboBox()
        self.combo_month.addItems(["2026-01","2026-02","2026-03","2026-04","2026-05","2026-06","2026-07","2026-08","2026-09","2026-10","2026-11","2026-12"])
        self.combo_month.setMinimumSize(200, 38)
        l.addWidget(self.combo_month, 0, Qt.AlignCenter)
        btn = QPushButton("导出 TXT")
        btn.setMinimumSize(200, 44)
        btn.setStyleSheet("background:#0078D4;color:#FFF;font-weight:bold;border:none;border-radius:6px;font-size:16pt;padding:10px;")
        btn.clicked.connect(self._export_txt)
        l.addWidget(btn, 0, Qt.AlignCenter)
        l.addStretch()
        return w

    def _export_txt(self):
        month = self.combo_month.currentText()
        dates = self.checkin_data.get("dates", [])
        md = [d for d in dates if d.startswith(month)]
        streak = get_consecutive_days(md)
        total = len(md)
        path = os.path.join(DATA_DIR, "report_" + month + ".txt")
        try:
            lines = []
            lines.append("==============================")
            lines.append("  守着你 \u00b7 签到报告")
            lines.append("==============================")
            lines.append("月份: " + month)
            lines.append("签到天数: " + str(total) + " / 30")
            lines.append("连续签到: " + str(streak) + " 天")
            rate = total / 30 * 100 if total > 0 else 0
            idx = "优秀" if rate >= 80 else "良好" if rate >= 50 else "需关注"
            lines.append("安心指数: " + idx)
            lines.append("")
            lines.append("签到日期:")
            for d in sorted(md):
                lines.append("  " + d)
            lines.append("")
            lines.append("-- 来自守着你安全助手")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            subprocess.run(["explorer", "/select,", path])
            QMessageBox.information(self, "成功", "报告已生成: " + path)
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))


def main():
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 14))
    app.setQuitOnLastWindowClosed(False)
    w = ProWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
