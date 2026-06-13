@echo off
chcp 65001 >nul
title 窗口置顶大师 · 专业版 - 打包脚本
echo ========================================
echo   窗口置顶大师 (TopMost Master) 专业版
echo   正在打包为 EXE ...
echo ========================================
echo.

pip install -r requirements.txt
pip install pyinstaller

echo.
echo 开始打包，请稍候...
echo.

pyinstaller --onefile --windowed --hidden-import keyboard --hidden-import pywin32 --name "TopMost_pro" main.py

echo.
echo ========================================
echo  打包完成！
echo  EXE 位于 dist\TopMost_pro.exe
echo ========================================
pause
