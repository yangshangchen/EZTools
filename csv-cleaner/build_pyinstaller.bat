@echo off
chcp 65001 >nul
title CSV/Excel 数据清洗工具 - PyInstaller 构建

echo ========================================
echo  CSV/Excel 数据清洗工具 - PyInstaller 构建
echo ========================================

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python
    pause & exit /b 1
)

:: 安装依赖
echo [1/3] 安装依赖...
python -m pip install -r requirements.txt --quiet

:: 安装 PyInstaller
echo [2/3] 安装 PyInstaller...
python -m pip install pyinstaller --quiet

:: 构建 EXE
echo [3/3] 正在构建 EXE（可能需要5-10分钟）...
python -m PyInstaller --onefile --windowed --name "CSV数据清洗工具" ^
    --clean --noconfirm --distpath dist ^
    --exclude PySide6 --exclude PySide2 --exclude PyQt6 ^
    --exclude torch --exclude tensorflow ^
    main.py

if errorlevel 0 (
    echo.
    echo ========================================
    echo  构建成功！
    echo  输出: %CD%\dist\CSV数据清洗工具.exe
    echo ========================================
) else (
    echo [错误] 构建失败
)
pause
