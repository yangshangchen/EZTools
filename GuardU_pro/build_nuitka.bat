@echo off
pip install -r requirements.txt nuitka
nuitka --standalone --onefile --windows-disable-console --enable-plugin=pyqt5 --lto=yes --remove-output --output-dir=dist main.py
pause
