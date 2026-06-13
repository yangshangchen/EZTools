# 视频封面截图工具

本地视频截图 + 水印桌面工具。

## 功能

- 上传 MP4/MOV/AVI 等视频文件
- 预览播放（播放/暂停/拖拽进度）
- 截取当前帧为 PNG
- 添加可选文字水印（右下角，半透明背景）
- 自动命名：视频名_帧号_时间戳.png

## 直接运行

双击 \视频截图工具.exe\ 即可。

## 从源码运行

\\\ash
cd E:\赚钱小工具\video_capture
pip install -r requirements.txt
python main.py
\\\

## 依赖

PyQt5 / OpenCV / Pillow
