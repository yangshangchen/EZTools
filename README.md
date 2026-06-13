# ⚡ 效率工具箱 EZTools

> 🧰 8 款 Windows 本地效率工具 · 绿色免安装 · 源码开放

---

## 📦 工具列表

| # | 工具 | 功能 | 大小 |
|---|------|------|------|
| 1 | **CSV数据清洗工具** | CSV/Excel 互转、去重、筛选、编码检测 | 186 MB |
| 2 | **LightningSearch Pro** | 全盘文件搜索、批量操作、导出报告 | 186 MB |
| 3 | **LightningSearch Free** | 轻量文件搜索（100条限制） | 36 MB |
| 4 | **PDF 工具箱** | PDF 合并/拆分/页面提取 | 59 MB |
| 5 | **图片批量压缩工具** | 批量压缩图片，导出 ZIP | 56 MB |
| 6 | **批量重命名工具** | 文件批量重命名，支持撤销 | 35 MB |
| 7 | **文件夹同步备份工具** | 镜像/增量同步，MD5 校验 | 35 MB |
| 8 | **视频截图工具** | 视频帧截取，支持水印 | 93 MB |

**全部工具特点：**
- 🟢 绿色免安装，双击即用
- 🔒 100% 本地运行，不上传任何数据
- 🎨 纯白高对比度 UI，长时间使用不伤眼
- 🇨🇳 完美支持中文路径和文件名
- 🆓 LightningSearch Free 永久免费

---

## ⬇️ 下载

预编译 EXE 存放在 [`工具包/`](工具包/) 目录，下载后直接双击运行。

**百度网盘：** https://github.com/yangshangchen/EZTools/releases/tag/v1.0.0
**123云盘：** https://github.com/yangshangchen/EZTools/releases/tag/v1.0.0

---

## 🛠️ 从源码构建

需要 Python 3.9+ 和以下依赖：

```bash
pip install PyQt5 pandas numpy openpyxl chardet xlrd numba pillow qrcode opencv-python-headless PyMuPDF cryptography requests
```

各工具独立打包：

```bash
# Python 3.9+ 环境
pip install pyinstaller

# 打包单个工具（示例）
cd csv-cleaner
pyinstaller --onefile --windowed --name "CSV数据清洗工具" main.py
```

---

## ☕ 支持作者

如果这些工具帮到了你，欢迎请作者喝杯咖啡 ☕

微信 / 支付宝：[详见 打赏页.html 或 https://eztools-616.netlify.app/donate.html]

---


## 📞 联系作者

- 📱 微信: ysc06crush
- 💬 QQ: 640251334
- 🌐 GitHub: https://github.com/yangshangchen/EZTools

---

## 📄 协议

本项目源码采用 **MIT License** 开源，EXE 可自由分发。

`SPDX-License-Identifier: MIT`

---

## 🌐 在线资源

- **GitHub 仓库:** https://github.com/yangshangchen/EZTools
- **产品页:** https://eztools-616.netlify.app
- **打赏页:** https://eztools-616.netlify.app/donate.html
- **下载 Release:** https://github.com/yangshangchen/EZTools/releases/tag/v1.0.0

