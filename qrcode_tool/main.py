# -*- coding: utf-8 -*-
"""
本地二维码工具箱
功能：生成 / 批量生成 / 解析二维码
所有操作本地完成，无网络请求
"""

import sys
import os
import io
import re
import zipfile
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QSlider, QTextEdit,
    QFileDialog, QMessageBox, QCheckBox, QFrame, QScrollArea,
    QSizePolicy, QSpacerItem, QPlainTextEdit
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import (
    QPixmap, QImage, QColor, QFont, QPalette, QIcon, QFontDatabase
)

import qrcode
from PIL import Image, ImageDraw
import cv2

# ── 常量 ──────────────────────────────────────────────────────────────
ERROR_CORRECTION_MAP = {
    "L (7%)":  qrcode.constants.ERROR_CORRECT_L,
    "M (15%)": qrcode.constants.ERROR_CORRECT_M,
    "Q (25%)": qrcode.constants.ERROR_CORRECT_Q,
    "H (30%)": qrcode.constants.ERROR_CORRECT_H,
}
DEFAULT_FG = "#000000"
DEFAULT_BG = "#FFFFFF"
MAX_LOGO_SIZE = 100
DEFAULT_QR_SIZE = 280
SAVE_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "QRCodeTool")


# ── 工具函数 ──────────────────────────────────────────────────────────

def sanitize_filename(text: str, max_len: int = 40) -> str:
    """去除文件名非法字符，截断到 max_len。"""
    name = text.strip().replace("\n", "_").replace("\r", "")
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r'\s+', "_", name)
    if len(name) > max_len:
        name = name[:max_len]
    return name or "qrcode"


def pil_to_pixmap(pil_img: Image.Image, target_size: int = None) -> QPixmap:
    """PIL Image → QPixmap，可选缩放到 target_size。"""
    if target_size:
        pil_img = pil_img.resize((target_size, target_size), Image.LANCZOS)
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


def overlay_logo(qr_img: Image.Image, logo: Image.Image) -> Image.Image:
    """将 Logo 居中覆盖到二维码上，Logo 最大 100×100 且不超过二维码 1/4。"""
    qr_w, qr_h = qr_img.size
    max_logo = min(MAX_LOGO_SIZE, qr_w // 4, qr_h // 4)
    logo = logo.copy()
    logo.thumbnail((max_logo, max_logo), Image.LANCZOS)

    # 在 Logo 底部加白色衬底（提高识别率）
    bg = Image.new("RGBA", logo.size, (255, 255, 255, 200))
    pos = ((qr_w - logo.width) // 2, (qr_h - logo.height) // 2)

    qr_img = qr_img.convert("RGBA")
    qr_img.paste(bg, pos, bg)
    if logo.mode == "RGBA":
        qr_img.paste(logo, pos, logo)
    else:
        qr_img.paste(logo, pos)
    return qr_img.convert("RGB")


def decode_qr_from_image(file_path: str) -> tuple:
    """Decode QR code with PIL preprocessing + OpenCV multi-strategy."""
    import numpy as np
    from PIL import Image, ImageEnhance, ImageFilter as PILFilter

    info_log = []

    def load_image(fp):
        img = cv2.imread(fp)
        if img is not None:
            info_log.append(f"OpenCV: loaded {img.shape}")
            return img
        try:
            pil = Image.open(fp).convert("RGB")
            arr = np.array(pil)
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            info_log.append(f"PIL: loaded {bgr.shape}")
            return bgr
        except Exception as e:
            info_log.append(f"PIL failed: {e}")
            return None

    def try_decode(img, label):
        if img is None or img.size == 0:
            return None
        detector = cv2.QRCodeDetector()
        try:
            result, points, _ = detector.detectAndDecode(img)
            if result:
                info_log.append(f"OK [{label}]")
                return result
        except Exception:
            pass
        return None

    def variants_from_gray(gray):
        v = []
        v.append(("gray", gray))
        v.append(("inv", cv2.bitwise_not(gray)))
        for bs in [31, 51, 71]:
            try:
                th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                            cv2.THRESH_BINARY, bs, 2)
                v.append((f"adp_{bs}", th))
            except:
                pass
        try:
            _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            v.append(("otsu", otsu))
        except:
            pass
        return v

    # Load
    img_bgr = load_image(file_path)
    if img_bgr is None:
        return False, "无法加载图片"

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    strategies = [("bgr", img_bgr)]

    # Grayscale variants
    for name, v in variants_from_gray(gray):
        strategies.append((name, v))

    # Median blur (removes grid/noise while preserving edges)
    for ksize in [3, 5, 7, 9, 11]:
        median = cv2.medianBlur(gray, ksize)
        strategies.append((f"median_{ksize}", median))

    # Gaussian blur (for very noisy images)
    for ksize in [(3,3), (5,5)]:
        gauss = cv2.GaussianBlur(gray, ksize, 0)
        strategies.append((f"gauss_{ksize[0]}", gauss))

    # Morphological operations
    for ksize in [(3,3), (5,5)]:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, ksize)
        opened = cv2.morphologyEx(gray, cv2.MORPH_OPEN, kernel)
        strategies.append((f"open_{ksize[0]}", opened))
        closed = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
        strategies.append((f"close_{ksize[0]}", closed))

    # Scaled up
    for scale in [1.5, 2.0]:
        scaled = cv2.resize(gray, (int(w*scale), int(h*scale)), cv2.INTER_CUBIC)
        strategies.append((f"scale_{scale}x", scaled))

    # PIL preprocessing
    try:
        pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
        for name, enh in [("sharp", ImageEnhance.Sharpness(pil).enhance(2.0)),
                          ("contrast", ImageEnhance.Contrast(pil).enhance(1.5)),
                          ("edges", pil.filter(PILFilter.EDGE_ENHANCE_MORE))]:
            arr = cv2.cvtColor(np.array(enh), cv2.COLOR_RGB2GRAY)
            strategies.append((name, arr))
    except Exception:
        pass

    # Try all
    for name, img_data in strategies:
        result = try_decode(img_data, name)
        if result:
            return True, result

    # Last resort: detect + decode
    try:
        det = cv2.QRCodeDetector()
        res, pts = det.detect(img_bgr)
        if pts is not None and len(pts) > 0:
            res, straight = det.decode(img_bgr, pts)
            if res:
                info_log.append("OK [detect+decode]")
                return True, res
    except Exception:
        pass

    info_msg = " | ".join(info_log[-4:])
    return False, f"未检测到二维码\n({info_msg})"


# ── 主窗口 ────────────────────────────────────────────────────────────

class QRCodeTool(QMainWindow):
    def __init__(self):
        super().__init__()
        os.makedirs(SAVE_DIR, exist_ok=True)
        self.current_qr_pil = None          # 当前生成的 PIL Image
        self.logo_pil = None                # 当前 Logo 的 PIL Image
        self.fg_color = DEFAULT_FG
        self.bg_color = DEFAULT_BG

        self._init_ui()

    # ── UI 初始化 ──────────────────────────────────────────────────

    def _init_ui(self):
        self.setWindowTitle("二维码工具箱")
        self.setObjectName("mainWindow")
        self.resize(1280, 860)
        self.setMinimumSize(1024, 700)

        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(14)

        # ─ 标题栏 ───────────────────────────────────────────────
        title_bar = QWidget()
        title_bar.setObjectName("panelGlass")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(18, 10, 18, 10)

        title_label = QLabel("🔲  二维码工具箱")
        title_label.setObjectName("titleLabel")
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        self.top_check = QCheckBox("总在最前")
        self.top_check.stateChanged.connect(self._toggle_top)
        title_layout.addWidget(self.top_check)

        main_layout.addWidget(title_bar)

        # ─ 左右分栏 ──────────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(16)

        # ──── 左侧：生成 / 批量 ───────────────────────────────────
        left_panel = QFrame()
        left_panel.setObjectName("panelGlass")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(18, 16, 18, 16)
        left_layout.setSpacing(12)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        left_content = QWidget()
        left_content.setStyleSheet("background: transparent;")
        self.left_form = QVBoxLayout(left_content)
        self.left_form.setContentsMargins(0, 0, 0, 0)
        self.left_form.setSpacing(8)
        left_scroll.setWidget(left_content)

        self._build_left_panel()

        left_layout.addWidget(left_scroll)
        body.addWidget(left_panel, stretch=55)

        # ──── 右侧：解析 ──────────────────────────────────────────
        right_panel = QFrame()
        right_panel.setObjectName("panelGlass")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(18, 16, 18, 16)
        right_layout.setSpacing(12)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        right_content = QWidget()
        right_content.setStyleSheet("background: transparent;")
        self.right_form = QVBoxLayout(right_content)
        self.right_form.setContentsMargins(0, 0, 0, 0)
        self.right_form.setSpacing(8)
        right_scroll.setWidget(right_content)

        self._build_right_panel()

        right_layout.addWidget(right_scroll)
        body.addWidget(right_panel, stretch=45)

        main_layout.addLayout(body)
        self.setStyleSheet(GLASS_STYLE)

    # ── 左侧面板内容 ──────────────────────────────────────────────

    def _build_left_panel(self):
        f = self.left_form

        # --- 输入 ---
        sec = QLabel("✏️ 生成二维码")
        sec.setObjectName("sectionLabel")
        f.addWidget(sec)

        f.addWidget(QLabel("文本 / 链接"))
        self.input_text = QLineEdit()
        self.input_text.setPlaceholderText("输入文本或链接…")
        f.addWidget(self.input_text)

        # --- 颜色 ---
        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        self.fg_btn = QPushButton("前景色")
        self.fg_btn.setStyleSheet(
            f"background: {DEFAULT_FG}; color: #ffffff; border: 2px solid #5a5a78; font-weight: bold;"
        )
        self.fg_btn.setFixedSize(48, 28)
        self.fg_btn.clicked.connect(lambda: self._pick_color("fg"))
        color_row.addWidget(QLabel("前景"))
        color_row.addWidget(self.fg_btn)

        self.bg_btn = QPushButton("背景色")
        self.bg_btn.setStyleSheet(
            f"background: {DEFAULT_BG}; color: #000000; border: 2px solid #5a5a78; font-weight: bold;"
        )
        self.bg_btn.setFixedSize(48, 28)
        self.bg_btn.clicked.connect(lambda: self._pick_color("bg"))
        color_row.addWidget(QLabel("背景"))
        color_row.addWidget(self.bg_btn)
        color_row.addStretch()
        f.addLayout(color_row)

        # --- 容错率 & 大小 ---
        opts_row = QHBoxLayout()
        opts_row.setSpacing(10)
        opts_row.addWidget(QLabel("容错率"))
        self.ec_combo = QComboBox()
        for k in ERROR_CORRECTION_MAP:
            self.ec_combo.addItem(k)
        self.ec_combo.setCurrentText("H (30%)")
        opts_row.addWidget(self.ec_combo)
        opts_row.addWidget(QLabel("大小"))
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(120, 500)
        self.size_slider.setValue(DEFAULT_QR_SIZE)
        self.size_slider.setFixedWidth(120)
        opts_row.addWidget(self.size_slider)
        self.size_label = QLabel(str(DEFAULT_QR_SIZE))
        self.size_label.setFixedWidth(30)
        opts_row.addWidget(self.size_label)
        self.size_slider.valueChanged.connect(
            lambda v: self.size_label.setText(str(v))
        )
        opts_row.addStretch()
        f.addLayout(opts_row)

        # --- Logo ---
        logo_row = QHBoxLayout()
        logo_row.setSpacing(6)
        self.logo_btn = QPushButton("选择 Logo")
        self.logo_btn.clicked.connect(self._pick_logo)
        logo_row.addWidget(self.logo_btn)
        self.logo_clear = QPushButton("清除")
        self.logo_clear.setObjectName("btnDanger")
        self.logo_clear.clicked.connect(self._clear_logo)
        logo_row.addWidget(self.logo_clear)
        self.logo_status = QLabel("未选择")
        self.logo_status.setStyleSheet("color: #8888aa;")
        logo_row.addWidget(self.logo_status)
        logo_row.addStretch()
        f.addLayout(logo_row)

        # --- 生成 ---
        self.gen_btn = QPushButton("生成二维码")
        self.gen_btn.setObjectName("btnPrimary")
        self.gen_btn.clicked.connect(self._generate_qr)
        f.addWidget(self.gen_btn)

        # --- 预览 ---
        self.qr_preview = QLabel()
        self.qr_preview.setAlignment(Qt.AlignCenter)
        self.qr_preview.setFixedHeight(300)
        self.qr_preview.setStyleSheet(
            "background: #1a1a2e; border-radius: 8px; border: 1px solid #3a3a55;"
        )
        self.qr_preview.setText("点击「生成二维码」预览")
        f.addWidget(self.qr_preview)

        # --- 下载单张 ---
        dl_row = QHBoxLayout()
        dl_row.setSpacing(6)
        self.dl_btn = QPushButton("📥 下载 PNG")
        self.dl_btn.setObjectName("btnPrimary")
        self.dl_btn.clicked.connect(self._download_single)
        self.dl_btn.setEnabled(False)
        dl_row.addWidget(self.dl_btn)

        self.copy_btn = QPushButton("📋 复制到剪贴板")
        self.copy_btn.clicked.connect(self._copy_qr)
        self.copy_btn.setEnabled(False)
        dl_row.addWidget(self.copy_btn)
        dl_row.addStretch()
        f.addLayout(dl_row)

        # ─── 分隔线 ─────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #3a3a55; background: #3a3a55;")
        f.addWidget(sep)

        # --- 批量 ---
        sec2 = QLabel("📦 批量生成")
        sec2.setObjectName("sectionLabel")
        f.addWidget(sec2)

        f.addWidget(QLabel("每行一个链接 / 文本"))
        self.batch_input = QPlainTextEdit()
        self.batch_input.setPlaceholderText(
            "https://example.com\nhttps://google.com\nhttps://github.com"
        )
        self.batch_input.setFixedHeight(130)
        f.addWidget(self.batch_input)

        self.batch_btn = QPushButton("⬇️ 批量生成并打包 ZIP")
        self.batch_btn.setObjectName("btnPrimary")
        self.batch_btn.clicked.connect(self._batch_generate)
        f.addWidget(self.batch_btn)

        f.addStretch()

    # ── 右侧面板内容 ──────────────────────────────────────────────

    def _build_right_panel(self):
        f = self.right_form

        sec = QLabel("📷 解析二维码")
        sec.setObjectName("sectionLabel")
        f.addWidget(sec)

        f.addWidget(QLabel("上传包含二维码的图片"))
        self.upload_btn = QPushButton("选择图片")
        self.upload_btn.clicked.connect(self._upload_for_decode)
        f.addWidget(self.upload_btn)

        self.decode_preview = QLabel()
        self.decode_preview.setAlignment(Qt.AlignCenter)
        self.decode_preview.setFixedHeight(250)
        self.decode_preview.setStyleSheet(
            "background: #1a1a2e; border-radius: 8px; border: 1px solid #3a3a55;"
        )
        self.decode_preview.setText("选择图片后预览")
        f.addWidget(self.decode_preview)

        # Paste from clipboard
        paste_row = QHBoxLayout()
        paste_row.setSpacing(6)
        self.decode_btn = QPushButton("7调 解码")
        self.decode_btn.setObjectName("btnPrimary")
        self.decode_btn.clicked.connect(self._decode_image)
        self.decode_btn.setEnabled(False)
        paste_row.addWidget(self.decode_btn)

        self.paste_btn = QPushButton("8cbc 粘贴图片")
        self.paste_btn.setObjectName("btnPrimary")
        self.paste_btn.clicked.connect(self._paste_decode)
        paste_row.addWidget(self.paste_btn)
        paste_row.addStretch()
        f.addLayout(paste_row)
        f.addStretch()

    # ── 事件处理 ──────────────────────────────────────────────────

    # ─ 总在前 ─
    def _toggle_top(self, state):
        if state == Qt.Checked:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()

    # ─ 选颜色 ─
    def _pick_color(self, target):
        from PyQt5.QtWidgets import QColorDialog
        initial = QColor(self.fg_color if target == "fg" else self.bg_color)
        color = QColorDialog.getColor(initial, self, "选择颜色")
        if color.isValid():
            hex_color = color.name()
            btn = self.fg_btn if target == "fg" else self.bg_btn
            # Auto choose black or white text based on luminance
            luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
            text_color = "#000000" if luminance > 140 else "#ffffff"
            btn.setStyleSheet(
                f"background: {hex_color}; color: {text_color}; "
                f"border: 2px solid #5a5a78; font-weight: bold;"
            )
            if target == "fg":
                self.fg_color = hex_color
            else:
                self.bg_color = hex_color

    # ─ 选 Logo ─
    def _pick_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Logo 图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tiff *.tif)"
        )
        if not path:
            return
        try:
            logo = Image.open(path)
            w, h = logo.size
            if w > MAX_LOGO_SIZE or h > MAX_LOGO_SIZE:
                logo.thumbnail((MAX_LOGO_SIZE, MAX_LOGO_SIZE), Image.LANCZOS)
                self.logo_status.setText(f"已缩放 ({min(w, MAX_LOGO_SIZE)}×{min(h, MAX_LOGO_SIZE)})")
            else:
                self.logo_status.setText("已选择")
            self.logo_pil = logo
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法加载图片: {e}")

    def _clear_logo(self):
        self.logo_pil = None
        self.logo_status.setText("未选择")

    # ─ 生成 ─
    def _generate_qr(self):
        text = self.input_text.text().strip()
        if not text:
            QMessageBox.information(self, "提示", "请输入文本或链接")
            return

        try:
            ec_key = self.ec_combo.currentText()
            ec = ERROR_CORRECTION_MAP.get(ec_key, qrcode.constants.ERROR_CORRECT_H)

            qr = qrcode.QRCode(
                version=None,
                error_correction=ec,
                box_size=10,
                border=2,
            )
            qr.add_data(text)
            qr.make(fit=True)

            # 生成原始 QR（PIL）
            img = qr.make_image(fill_color=self.fg_color, back_color=self.bg_color)
            pil_img = img.get_image().convert("RGB")

            # 叠加 Logo
            if self.logo_pil:
                pil_img = overlay_logo(pil_img, self.logo_pil)

            # 缩放到用户指定大小
            target = self.size_slider.value()
            pil_img = pil_img.resize((target, target), Image.LANCZOS)

            self.current_qr_pil = pil_img
            self.current_qr_text = text

            # 显示
            px = pil_to_pixmap(pil_img)
            self.qr_preview.setPixmap(px)
            self.dl_btn.setEnabled(True)
            self.copy_btn.setEnabled(True)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成失败: {e}")

    # ─ 下载单张 ─
    def _download_single(self):
        if self.current_qr_pil is None:
            return

        name = sanitize_filename(self.current_qr_text, 20)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{name}_{ts}.png"

        path, _ = QFileDialog.getSaveFileName(
            self, "保存二维码", os.path.join(SAVE_DIR, default_name),
            "PNG 图片 (*.png)"
        )
        if path:
            self.current_qr_pil.save(path, "PNG")
            QMessageBox.information(self, "完成", f"已保存:\n{path}")

    # ─ 复制到剪贴板 ─
    def _copy_qr(self):
        if self.current_qr_pil is None:
            return
        from PyQt5.QtWidgets import QApplication
        px = pil_to_pixmap(self.current_qr_pil)
        QApplication.clipboard().setPixmap(px)

    # ─ 批量 ─
    def _batch_generate(self):
        text = self.batch_input.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "请在批量输入框中输入内容")
            return

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            QMessageBox.information(self, "提示", "未检测到有效内容")
            return
        if len(lines) > 200:
            reply = QMessageBox.question(
                self, "确认", f"共 {len(lines)} 条链接，可能较慢，是否继续？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        try:
            ec_key = self.ec_combo.currentText()
            ec = ERROR_CORRECTION_MAP.get(ec_key, qrcode.constants.ERROR_CORRECT_H)
            target = self.size_slider.value()

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for idx, line in enumerate(lines, 1):
                    qr = qrcode.QRCode(
                        version=None, error_correction=ec,
                        box_size=10, border=2,
                    )
                    qr.add_data(line)
                    qr.make(fit=True)
                    img = qr.make_image(
                        fill_color=self.fg_color, back_color=self.bg_color
                    )
                    pil_img = img.get_image().convert("RGB")

                    if self.logo_pil:
                        pil_img = overlay_logo(pil_img, self.logo_pil)

                    pil_img = pil_img.resize((target, target), Image.LANCZOS)

                    name = sanitize_filename(line, 16) or f"qrcode_{idx}"
                    buf = io.BytesIO()
                    pil_img.save(buf, "PNG")
                    zf.writestr(f"{name}_{idx}.png", buf.getvalue())

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_zip = f"二维码批量_{ts}.zip"
            save_path, _ = QFileDialog.getSaveFileName(
                self, "保存 ZIP 包", os.path.join(SAVE_DIR, default_zip),
                "ZIP 文件 (*.zip)"
            )
            if save_path:
                with open(save_path, "wb") as f:
                    f.write(zip_buffer.getvalue())
                QMessageBox.information(
                    self, "完成",
                    f"成功生成 {len(lines)} 个二维码\n已打包到:\n{save_path}"
                )

        except Exception as e:
            QMessageBox.critical(self, "错误", f"批量生成失败: {e}")

    # ─ 上传解码图片 ─
    def _upload_for_decode(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择二维码图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tiff *.tif)"
        )
        if not path:
            return
        self._decode_file_path = path

        # 预览
        px = QPixmap(path)
        if px.isNull():
            QMessageBox.warning(self, "错误", "无法加载图片")
            return
        scaled = px.scaled(
            260, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.decode_preview.setPixmap(scaled)
        self.decode_btn.setEnabled(True)

    # ─ 解码 ─
    def _decode_image(self):
        if not self._decode_file_path:
            return
        success, result = decode_qr_from_image(self._decode_file_path)
        if success:
            self.decode_result.setText(result)
            self.decode_result.setStyleSheet("color: #7ac07a; font-weight: bold;")
        else:
            self.decode_result.setText(result)
            self.decode_result.setStyleSheet("color: #e8a060; font-weight: bold;")

    # 8cbc 粘贴解码
    def _paste_decode(self):
        """Paste image from clipboard and decode QR code."""
        from PyQt5.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        pixmap = clipboard.pixmap()
        if pixmap is None or pixmap.isNull():
            QMessageBox.information(self, "提示", "剪贴板中没有图片")
            return

        # Save to temp file
        import tempfile, os
        tmp = os.path.join(tempfile.gettempdir(), "clipboard_qr.png")
        pixmap.save(tmp, "PNG")

        # Show preview
        scaled = pixmap.scaled(260, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.decode_preview.setPixmap(scaled)

        self._decode_file_path = tmp
        self.decode_btn.setEnabled(True)

        # Auto decode
        success, result = decode_qr_from_image(self._decode_file_path)
        if success:
            self.decode_result.setText(result)
            self.decode_result.setStyleSheet("color: #7ac07a; font-weight: bold;")
        else:
            self.decode_result.setText(result)
            self.decode_result.setStyleSheet("color: #e8a060; font-weight: bold;")
# ── 入口