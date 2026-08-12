@echo off
setlocal
cd /d "%~dp0"
set "GUI_PYTHONW=C:\Users\dongqiyu\anaconda3\envs\ortools_env\pythonw.exe"
if not exist "%GUI_PYTHONW%" (
  echo Required interpreter not found: %GUI_PYTHONW%
  pause
  exit /b 1
)
start "3D Container Loading" /b "%GUI_PYTHONW%" -m gui.app %*
endlocal
