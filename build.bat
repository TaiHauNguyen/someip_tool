@echo off
rem Double-click to build the executables into dist\.
rem Any argument is passed straight to build_exe.py (--onedir, --clean, --gui, --cli).
setlocal
cd /d "%~dp0"

rem Find an interpreter.  A bare "python" can be the Microsoft Store stub, which
rem opens the Store and reports success, so ask it to prove it runs.
set "PY="
python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (
  echo.
  echo   Python was not found.
  echo   Install it from https://www.python.org/downloads/ and tick
  echo   "Add python.exe to PATH", then run this again.
  echo.
  pause
  exit /b 1
)

%PY% build_exe.py %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo   Build failed - the message above says why.
pause
exit /b %RC%
