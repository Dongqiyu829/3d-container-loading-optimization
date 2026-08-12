@echo off
setlocal
cd /d "%~dp0"
set "GUI_PYTHON=C:\Users\dongqiyu\anaconda3\envs\ortools_env\python.exe"
if not exist "%GUI_PYTHON%" (
  echo Required interpreter not found: %GUI_PYTHON%
  if not "%GUI_NO_PAUSE%"=="1" pause
  exit /b 1
)
"%GUI_PYTHON%" -m gui.app %*
set "GUI_EXIT_CODE=%ERRORLEVEL%"
if not "%GUI_NO_PAUSE%"=="1" pause
exit /b %GUI_EXIT_CODE%
