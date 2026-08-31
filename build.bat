@echo off
rem Double-click to build the executables into dist\.
rem Any argument is passed straight to build_exe.py (--onedir, --clean, ...).
setlocal
cd /d "%~dp0"
python build_exe.py %*
echo.
pause
