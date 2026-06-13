#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
本地视频封面截图工具
上传视频 → 预览播放 → 截取帧 → 加水印 → 下载 PNG
"""

import sys
import os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QLineEdit, QFileDialog,
    QMessageBox, QCheckBox, QFrame, QTextEdit
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap, QImage, QFont, QFontDatabase

# ── 常量 ──────────────────────────────────────────────────────────────
SAVE_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "VideoCapture")
PREVIEW_W = 720
PREVIEW_H = 480
THUMB_W = 320
THUMB_H = 240


# ── 工具函数 ──────────────────────────────────────────────────────────

def pil_to_pixmap(pil_img: Image.Image, max_w=None, max_h=None) -> QPixmap:
    """PIL Image → QPixmap，可选缩放。"""
    if max_w and max_h:
        pil_img.thumbnail((max_w, max_h), Image.LANCZOS)
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


def cvframe_to_pil(frame_bgr) -> Image.Image:
    """OpenCV BGR frame → PIL RGB."""
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def add_watermark(pil_img: Image.Image, text: str) -> Image.Image:
    """在图片右下角添加文字水印。"""
    if not text.strip():
        return pil_img
    img = pil_img.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # 自适应字号（图片宽度的 1/25）
    font_size = max(14, img.width // 25)
    try:
        font = ImageFont.truetype("msyh.ttc", font_size)
    except (IOError, OSError):
        try:
            font = ImageFont.truetype("simhei.ttf", font_size)
        except (IOError, OSError):
            font = ImageFont.load_default()

    # 文字尺寸
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # 右下角位置（留边距）
    margin = 12
    x = img.width - tw - margin
    y = img.height - th - margin

    # 半透明黑底
    bg_pad = 6
    draw.rectangle(
        [x - bg_pad, y - bg_pad, x + tw + bg_pad, y + th + bg_pad],
        fill=(0, 0, 0, 160)
    )
    # 白色文字
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    return Image.alpha_composite(img, overlay).convert("RGB")


def format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ── 深色主题 QSS ──────────────────────────────────────────────────────

WHITE_STYLE = """
QMainWindow {
    background: #FFFFFF;
}
QWidget#centralWidget {
    background: transparent;
}
QFrame#panel {
    background: #FFFFFF;
    border: 2px solid #CCCCCC;
    border-radius: 10px;
}
QLabel {
    color: #000000;
    font-size: 14pt;
    background: transparent;
    padding: 2px 0;
    font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
}
QLabel#titleLabel {
    font-size: 20pt;
    font-weight: bold;
    color: #000000;
    padding: 6px 0;
}
QLabel#sectionLabel {
    font-size: 16pt;
    font-weight: 600;
    color: #333333;
    padding: 4px 0;
}
QLineEdit, QTextEdit {
    background: #FFFFFF;
    border: 2px solid #CCCCCC;
    border-radius: 6px;
    color: #000000;
    padding: 7px 10px;
    font-size: 14pt;
    font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
}
QLineEdit:focus, QTextEdit:focus {
    border-color: #0078D4;
    border-width: 3px;
}
QPushButton {
    background: #0078D4;
    border: none;
    border-radius: 8px;
    color: #FFFFFF;
    padding: 9px 18px;
    font-size: 16pt;
    font-weight: bold;
    min-height: 22px;
    font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
}
QPushButton:hover {
    background: #106EBE;
}
QPushButton:pressed {
    background: #005A9E;
}
QPushButton#btnPrimary {
    background: #0078D4;
    border: none;
    font-weight: bold;
}
QPushButton#btnPrimary:hover {
    background: #106EBE;
}
QPushButton#btnPlay {
    font-size: 18pt;
    min-width: 48px;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #E0E0E0;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #0078D4;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}
QSlider::handle:horizontal:hover {
    background: #106EBE;
}
QSlider::sub-page:horizontal {
    background: #0078D4;
    border-radius: 3px;
}
QCheckBox {
    color: #000000;
    font-size: 14pt;
    spacing: 8px;
    font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
}
QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border: 2px solid #CCCCCC;
    border-radius: 4px;
    background: #FFFFFF;
}
QCheckBox::indicator:checked {
    background: #0078D4;
    border-color: #0078D4;
}
QScrollBar:vertical {
    width: 10px;
    background: #F0F0F0;
}
QScrollBar::handle:vertical {
    background: #CCCCCC;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #AAAAAA;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
"""


# ── 主窗口 ────────────────────────────────────────────────────────────

class VideoCaptureTool(QMainWindow):
    def __init__(self):
        super().__init__()
        os.makedirs(SAVE_DIR, exist_ok=True)

        self.cap = None               # cv2.VideoCapture
        self.video_path = ""
        self.total_frames = 0
        self.fps = 30.0
        self.current_frame_idx = 0
        self.is_playing = False
        self.last_captured_pil = None # 最近截取的 PIL Image

        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self._advance_frame)

        self._init_ui()

    # ── UI ────────────────────────────────────────────────────────

    def _init_ui(self):
        self.setWindowTitle("\u89c6\u9891\u5c01\u9762\u622a\u56fe\u5de5\u5177")
        self.setObjectName("mainWindow")
        self.resize(1000, 760)
        self.setMinimumSize(800, 640)

        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)
        ml.setContentsMargins(16, 12, 16, 12)
        ml.setSpacing(10)

        # ─ 标题栏 ───────────────────────────────────────────────
        title_bar = QFrame()
        title_bar.setObjectName("panel")
        tl = QHBoxLayout(title_bar)
        tl.setContentsMargins(14, 8, 14, 8)

        title_label = QLabel("\U0001f3ac  \u89c6\u9891\u5c01\u9762\u622a\u56fe\u5de5\u5177")
        title_label.setObjectName("titleLabel")
        tl.addWidget(title_label)
        tl.addStretch()

        self.top_check = QCheckBox("\u603b\u5728\u6700\u524d")
        self.top_check.stateChanged.connect(self._toggle_top)
        tl.addWidget(self.top_check)
        ml.addWidget(title_bar)

        # ─ 主内容 ───────────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(12)

        # ─── 左侧：视频 + 控制 ──────────────────────────────────
        left_panel = QFrame()
        left_panel.setObjectName("panel")
        ll = QVBoxLayout(left_panel)
        ll.setContentsMargins(14, 12, 14, 12)
        ll.setSpacing(8)

        upload_row = QHBoxLayout()
        upload_row.setSpacing(6)
        self.open_btn = QPushButton("\U0001f4c2  \u9009\u62e9\u89c6\u9891")
        self.open_btn.setObjectName("btnPrimary")
        self.open_btn.clicked.connect(self._open_video)
        upload_row.addWidget(self.open_btn)
        self.file_label = QLabel("\u672a\u9009\u62e9\u89c6\u9891")
        self.file_label.setStyleSheet("color: #8888aa;")
        upload_row.addWidget(self.file_label)
        upload_row.addStretch()
        ll.addLayout(upload_row)

        # 视频预览
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(PREVIEW_W, PREVIEW_H)
        self.preview_label.setStyleSheet(
            "background: #FFFFFF; border: 2px solid #CCCCCC; border-radius: 8px;"
        )
        self.preview_label.setText("\u9009\u62e9\u89c6\u9891\u540e\u663e\u793a\u9884\u89c8")
        ll.addWidget(self.preview_label)

        # 播放控制
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)

        self.play_btn = QPushButton("\u25b6")
        self.play_btn.setObjectName("btnPlay")
        self.play_btn.setFixedWidth(50)
        self.play_btn.clicked.connect(self._toggle_play)
        self.play_btn.setEnabled(False)
        ctrl_row.addWidget(self.play_btn)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._on_slider_change)
        self.slider.sliderPressed.connect(self._on_slider_press)
        self.slider.sliderReleased.connect(self._on_slider_release)
        ctrl_row.addWidget(self.slider)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setFixedWidth(130)
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ctrl_row.addWidget(self.time_label)
        ll.addLayout(ctrl_row)

        body.addWidget(left_panel, stretch=60)

        # ─── 右侧：截图 + 水印 ──────────────────────────────────
        right_panel = QFrame()
        right_panel.setObjectName("panel")
        rl = QVBoxLayout(right_panel)
        rl.setContentsMargins(14, 12, 14, 12)
        rl.setSpacing(8)

        sec = QLabel("\U0001f4f7  \u622a\u56fe")
        sec.setObjectName("sectionLabel")
        rl.addWidget(sec)

        # 截图预览
        self.capture_label = QLabel()
        self.capture_label.setAlignment(Qt.AlignCenter)
        self.capture_label.setMinimumSize(THUMB_W, THUMB_H)
        self.capture_label.setStyleSheet(
            "background: #FFFFFF; border: 2px solid #CCCCCC; border-radius: 8px;"
        )
        self.capture_label.setText("\u622a\u56fe\u540e\u663e\u793a\u9884\u89c8")
        rl.addWidget(self.capture_label)

        # 水印
        rl.addWidget(QLabel("\u6c34\u5370\u6587\u5b57\uff08\u53ef\u9009\uff09"))
        wm_row = QHBoxLayout()
        self.watermark_input = QLineEdit()
        self.watermark_input.setPlaceholderText("\u4f8b\u5982\uff1a\u00a9 \u516c\u53f8\u540d\u79f0 2026")
        wm_row.addWidget(self.watermark_input)
        self.wm_btn = QPushButton("\u9884\u89c8\u6c34\u5370")
        self.wm_btn.clicked.connect(self._preview_watermark)
        self.wm_btn.setEnabled(False)
        wm_row.addWidget(self.wm_btn)
        rl.addLayout(wm_row)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.capture_btn = QPushButton("\U0001f4f8  \u622a\u53d6\u5f53\u524d\u5e27")
        self.capture_btn.setObjectName("btnPrimary")
        self.capture_btn.clicked.connect(self._capture_frame)
        self.capture_btn.setEnabled(False)
        btn_row.addWidget(self.capture_btn)

        self.save_btn = QPushButton("\U0001f4e5  \u4e0b\u8f7d PNG")
        self.save_btn.setObjectName("btnPrimary")
        self.save_btn.clicked.connect(self._save_capture)
        self.save_btn.setEnabled(False)
        btn_row.addWidget(self.save_btn)
        rl.addLayout(btn_row)

        # 截取信息
        self.capture_info = QLabel("")
        self.capture_info.setStyleSheet("color: #8888aa; font-size: 12px;")
        rl.addWidget(self.capture_info)

        rl.addStretch()
        body.addWidget(right_panel, stretch=40)

        ml.addLayout(body)
        self.setStyleSheet(WHITE_STYLE)

    # ── 事件处理 ──────────────────────────────────────────────────

    def _toggle_top(self, state):
        if state == Qt.Checked:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()

    def _open_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "\u9009\u62e9\u89c6\u9891", "",
            "\u89c6\u9891\u6587\u4ef6 (*.mp4 *.mov *.avi *.mkv *.wmv *.flv *.webm)"
        )
        if not path:
            return

        # 关闭之前的
        if self.cap:
            self.cap.release()
        self.is_playing = False
        self.play_timer.stop()

        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            QMessageBox.warning(self, "\u9519\u8bef", "\u65e0\u6cd5\u6253\u5f00\u89c6\u9891\u6587\u4ef6")
            return

        self.video_path = path
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        if self.fps <= 0:
            self.fps = 30.0
        duration = self.total_frames / self.fps if self.fps > 0 else 0

        # 文件信息
        fname = os.path.basename(path)
        self.file_label.setText(f"{fname}  ({self.total_frames} \u5e27, {format_time(duration)})")
        self.file_label.setStyleSheet("color: #333333; font-size: 14pt;")

        # 滑块
        self.slider.setRange(0, max(0, self.total_frames - 1))
        self.slider.setValue(0)
        self.slider.setEnabled(True)
        self.play_btn.setEnabled(True)
        self.capture_btn.setEnabled(True)

        # 显示第一帧
        self.current_frame_idx = 0
        self._display_frame(0)

        # 更新截图区
        self.capture_label.setText("\u70b9\u51fb\u300c\u622a\u53d6\u5f53\u524d\u5e27\u300d\u83b7\u53d6\u622a\u56fe")
        self.save_btn.setEnabled(False)
        self.wm_btn.setEnabled(False)
        self.capture_info.setText("")
        self.last_captured_pil = None

    def _display_frame(self, frame_idx: int):
        """读取并显示指定帧。"""
        if self.cap is None:
            return
        idx = max(0, min(frame_idx, self.total_frames - 1))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = self.cap.read()
        if not ret:
            return

        self.current_frame_idx = idx
        pil_img = cvframe_to_pil(frame)
        px = pil_to_pixmap(pil_img, PREVIEW_W, PREVIEW_H)
        self.preview_label.setPixmap(px)

        # 更新时间显示
        seconds = idx / self.fps if self.fps > 0 else 0
        total_sec = self.total_frames / self.fps if self.fps > 0 else 0
        self.time_label.setText(f"{format_time(seconds)} / {format_time(total_sec)}")

    def _on_slider_change(self, value):
        """滑块值变化时（拖动或程序设置）。"""
        if not self.slider.isSliderDown():  # 用户拖动时由 _slider_release 处理
            return

    def _on_slider_press(self):
        self.play_timer.stop()
        self.is_playing = False
        self.play_btn.setText("\u25b6")

    def _on_slider_release(self):
        val = self.slider.value()
        self._display_frame(val)
        # 如果之前是在播放状态，继续播放
        if hasattr(self, '_was_playing') and self._was_playing:
            self._start_play()

    def _toggle_play(self):
        if self.cap is None:
            return
        if self.is_playing:
            self.play_timer.stop()
            self.is_playing = False
            self.play_btn.setText("\u25b6")
        else:
            self._start_play()

    def _start_play(self):
        if self.current_frame_idx >= self.total_frames - 1:
            self.current_frame_idx = 0
            self._display_frame(0)
            self.slider.setValue(0)
        interval = max(16, int(1000 / self.fps))
        self.play_timer.start(interval)
        self.is_playing = True
        self.play_btn.setText("\u23f8")

    def _advance_frame(self):
        """定时器回调：前进一帧。"""
        next_idx = self.current_frame_idx + 1
        if next_idx >= self.total_frames:
            self.play_timer.stop()
            self.is_playing = False
            self.play_btn.setText("\u25b6")
            return
        self._display_frame(next_idx)
        self.slider.setValue(next_idx)

    def _capture_frame(self):
        """截取当前帧。"""
        if self.cap is None:
            return

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame_idx)
        ret, frame = self.cap.read()
        if not ret:
            QMessageBox.warning(self, "\u9519\u8bef", "\u65e0\u6cd5\u83b7\u53d6\u5f53\u524d\u5e27")
            return

        pil_img = cvframe_to_pil(frame)

        # 如果有水印文字，加上
        wm_text = self.watermark_input.text().strip()
        if wm_text:
            pil_img = add_watermark(pil_img, wm_text)

        self.last_captured_pil = pil_img

        # 显示截图预览
        px = pil_to_pixmap(pil_img, THUMB_W, THUMB_H)
        self.capture_label.setPixmap(px)

        # 更新信息
        resolution = f"{pil_img.width}\u00d7{pil_img.height}"
        frame_info = f"\u7b2c {self.current_frame_idx} \u5e27"
        self.capture_info.setText(f"{frame_info} | {resolution}")
        self.capture_info.setStyleSheet("color: #7ac07a; font-size: 12px;")

        self.save_btn.setEnabled(True)
        self.wm_btn.setEnabled(True)

    def _preview_watermark(self):
        """重新生成带水印的预览。"""
        if self.last_captured_pil is None:
            # 如果没有截图，用当前预览帧
            self._capture_frame()
            return

        wm_text = self.watermark_input.text().strip()
        if not wm_text:
            # 无水印，重新显示原始截图
            if hasattr(self, '_raw_captured') and self._raw_captured is not None:
                px = pil_to_pixmap(self._raw_captured, THUMB_W, THUMB_H)
                self.capture_label.setPixmap(px)
                self.last_captured_pil = self._raw_captured
            self.save_btn.setEnabled(True)
            return

        # 重新截图（从原始帧）
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame_idx)
        ret, frame = self.cap.read()
        if not ret:
            return
        raw_pil = cvframe_to_pil(frame)
        self._raw_captured = raw_pil

        watermarked = add_watermark(raw_pil, wm_text)
        self.last_captured_pil = watermarked

        px = pil_to_pixmap(watermarked, THUMB_W, THUMB_H)
        self.capture_label.setPixmap(px)
        self.save_btn.setEnabled(True)

    def _save_capture(self):
        """保存截图。"""
        if self.last_captured_pil is None:
            return

        # 自动命名：视频名 + 帧号 + 时间戳
        vname = os.path.splitext(os.path.basename(self.video_path))[0]
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{vname}_frame{self.current_frame_idx}_{ts}.png"

        path, _ = QFileDialog.getSaveFileName(
            self, "\u4fdd\u5b58\u622a\u56fe", os.path.join(SAVE_DIR, default_name),
            "PNG \u56fe\u7247 (*.png)"
        )
        if path:
            self.last_captured_pil.save(path, "PNG")
            QMessageBox.information(self, "\u5b8c\u6210", f"\u5df2\u4fdd\u5b58:\n{path}")


# ── 入口 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    font = QFont()
    families = [
        "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI",
        "PingFang SC", "Noto Sans CJK SC", "sans-serif"
    ]
    for f in families:
        if f in QFontDatabase().families():
            font.setFamily(f)
            break
    font.setPointSize(10)
    app.setFont(font)

    window = VideoCaptureTool()
    window.show()
    sys.exit(app.exec_())

