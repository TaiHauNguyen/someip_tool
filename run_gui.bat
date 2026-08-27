@echo off
setlocal
cd /d "%~dp0"
python -c "import openpyxl" >nul 2>&1
if errorlevel 1 python -m pip install openpyxl
python gui.py %*
if errorlevel 1 pause
