@echo off
chcp 65001 >nul
title 批量重命名工具 - Nuitka 打包

echo ========================================
echo   批量重命名工具 - Nuitka 一键打包
echo ========================================
echo.

:: 1. Install deps
echo [1/3] 安装依赖...
python -m pip install PyQt5 nuitka -q
echo.

:: 2. Check compiler
echo [2/3] 检查 C 编译器...
where gcc >nul 2>nul
if errorlevel 1 (
    echo MinGW not found, checking MSVC...
    where cl >nul 2>nul
    if errorlevel 1 (
        echo WARNING: No C compiler detected.
        echo Nuitka needs either MinGW or MSVC.
        echo.
        echo Option 1: Install MinGW
        echo   winget install MartinStorsjo.LLVM-MinGW.UCRT
        echo.
        echo Option 2: Install MSVC Build Tools
        echo   winget install Microsoft.VisualStudio.2022.BuildTools --override ^"--wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended^"
        echo.
        pause
        exit /b 1
    ) else (
        echo Using MSVC compiler.
    )
) else (
    echo Using MinGW compiler.
)
echo.

:: 3. Build EXE with Nuitka
echo [3/3] 正在编译 EXE (可能需要 5-15 分钟)...
cd /d "%~dp0"
python -m nuitka ^
    --standalone ^
    --onefile ^
    --windows-disable-console ^
    --windows-icon-from-exe=python ^
    --enable-plugin=pyqt5 ^
    --output-dir=dist_nuitka ^
    --output-filename="批量重命名工具.exe" ^
    main.py

if errorlevel 1 (
    echo.
    echo 编译失败！
    echo 尝试使用 PyInstaller 作为备选：
    echo   pip install pyinstaller
    echo   pyinstaller --onefile --windowed --name "批量重命名工具" main.py
    pause
    exit /b 1
)

echo.
echo ========================================
echo   BUILD SUCCESS
echo ========================================
echo.
echo EXE: %~dp0dist_nuitka\批量重命名工具.exe
dir "%~dp0dist_nuitka\批量重命名工具.exe" 2>nul
echo.
echo 绿色免安装，双击即可运行。
echo.
pause
