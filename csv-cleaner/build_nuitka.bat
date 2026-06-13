@echo off
chcp 65001 >nul
title CSV/Excel 数据清洗工具 - Nuitka 构建

echo ========================================
echo  CSV/Excel 数据清洗工具 - Nuitka 构建
echo ========================================

:: 检查 Python 3.10+
py -3.10 --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 需要 Python 3.10+
    pause & exit /b 1
)

:: 安装依赖
echo [1/4] 安装依赖...
py -3.10 -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [警告] pip 安装失败，尝试继续...
)

:: 安装 Nuitka
echo [2/4] 安装 Nuitka...
py -3.10 -m pip install nuitka --quiet

:: 使用 Nuitka 编译
echo [3/4] 正在编译 EXE（可能需要5-10分钟）...
py -3.10 -m nuitka ^
    --standalone --onefile --windows-disable-console ^
    --enable-plugin=pyqt5 ^
    --lto=yes --remove-output --no-debug --low-memory ^
    --include-package=pandas --include-package=numpy ^
    --include-package=numba --include-package=openpyxl ^
    --include-package=chardet --include-package=xlrd ^
    --output-dir=dist ^
    --product-name="CSV_Excel数据清洗工具" ^
    --file-version=1.0.0 ^
    main.py

if errorlevel 0 (
    echo.
    echo ========================================
    echo  构建成功！
    echo  输出: %CD%\dist\main.exe
    echo  文件大小:
    dir %CD%\dist\main.exe
    echo ========================================
) else (
    echo [错误] 构建失败
    echo 尝试备用方案: PyInstaller
    echo py -3.10 -m pip install pyinstaller
    echo py -3.10 -m PyInstaller --onefile --windowed --name "CSV数据清洗工具" --clean main.py
)
pause
