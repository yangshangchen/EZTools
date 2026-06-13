@echo off
chcp 65001 >nul
title 文件夹同步备份工具 - 构建脚本

echo ========================================
echo   文件夹同步备份工具 - Nuitka 构建
echo ========================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)
echo [1/3] Python: OK

:: 安装依赖
echo [2/3] 安装依赖...
python -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [警告] pip 安装失败，尝试继续...
)

:: 检查 Nuitka
python -m pip install nuitka --quiet

:: 安装 Cython（Nuitka 推荐）
python -m pip install cython --quiet

:: 构建 EXE
echo [3/3] 正在构建 EXE（可能需要几分钟）...
python -m nuitka ^
    --standalone ^
    --onefile ^
    --windows-disable-console ^
    --windows-icon-from-ico=NONE ^
    --output-dir=dist ^
    --product-name=文件夹同步备份工具 ^
    --file-version=1.0.0 ^
    --enable-plugin=anti-bloat ^
    --remove-output ^
    --lto=no ^
    main.py

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo  构建成功！
    echo  输出: %CD%\dist\main.exe
    echo ========================================
) else (
    echo.
    echo [错误] 构建失败，请检查错误信息
)
pause
