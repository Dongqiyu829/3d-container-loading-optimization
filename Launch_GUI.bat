@echo off
setlocal
cd /d "%~dp0"
set "GUI_RUNTIME="
if defined GUI_PYTHONW set "GUI_RUNTIME=%GUI_PYTHONW%"
if not defined GUI_RUNTIME if exist ".venv\Scripts\pythonw.exe" set "GUI_RUNTIME=.venv\Scripts\pythonw.exe"
if not defined GUI_RUNTIME where pythonw.exe >nul 2>&1 && set "GUI_RUNTIME=pythonw.exe"
if not defined GUI_RUNTIME where python.exe >nul 2>&1 && set "GUI_RUNTIME=python.exe"
if not defined GUI_RUNTIME (
  echo No Python interpreter was found. Create .venv or add Python to PATH.
  pause
  exit /b 1
)
"%GUI_RUNTIME%" -c "import PySide6; import matplotlib; import ortools" >nul 2>&1
if errorlevel 1 (
  echo GUI dependencies are missing from %GUI_RUNTIME%.
  echo Install requirements.txt and requirements-gui.txt into that environment.
  pause
  exit /b 1
)
if "%GUI_LAUNCHER_CHECK_ONLY%"=="1" (
  echo GUI launcher environment check passed: %GUI_RUNTIME%
  exit /b 0
)
start "3D Container Loading" /b "%GUI_RUNTIME%" -m gui.app %*
endlocal
