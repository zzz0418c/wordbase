@echo off
rem vocabcurve launcher: prefer a working Python 3, fall back to the DSH runtime.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

python -c "import sys" >nul 2>nul
if not errorlevel 1 goto use_python

py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 goto use_py

set "DSHPY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if exist "%DSHPY%" goto use_dsh

echo Python 3.9+ not found. Install from https://www.python.org/downloads/
exit /b 1

:use_python
python -m vocabcurve %*
exit /b %errorlevel%

:use_py
py -3 -m vocabcurve %*
exit /b %errorlevel%

:use_dsh
"%DSHPY%" -m vocabcurve %*
exit /b %errorlevel%
