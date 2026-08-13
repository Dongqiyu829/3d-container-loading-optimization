@echo off
setlocal
cd /d "%~dp0"
set "GUI_RUNTIME="
if defined GUI_PYTHON set "GUI_RUNTIME=%GUI_PYTHON%"
if not defined GUI_RUNTIME if exist ".venv\Scripts\python.exe" set "GUI_RUNTIME=.venv\Scripts\python.exe"
if not defined GUI_RUNTIME where python.exe >nul 2>&1 && set "GUI_RUNTIME=python.exe"
if not defined GUI_RUNTIME (
  echo No Python interpreter was found. Create .venv or add Python to PATH.
  if not "%GUI_NO_PAUSE%"=="1" pause
  exit /b 1
)
"%GUI_RUNTIME%" -c "import PySide6; import matplotlib; import ortools"
if errorlevel 1 (
  echo GUI dependencies are missing from %GUI_RUNTIME%.
  echo Install requirements.txt and requirements-gui.txt into that environment.
  if not "%GUI_NO_PAUSE%"=="1" pause
  exit /b 1
)
if "%GUI_LAUNCHER_CHECK_ONLY%"=="1" (
  echo GUI launcher environment check passed: %GUI_RUNTIME%
  exit /b 0
)
"%GUI_RUNTIME%" -m gui.app %*
set "GUI_EXIT_CODE=%ERRORLEVEL%"
if not "%GUI_NO_PAUSE%"=="1" pause
exit /b %GUI_EXIT_CODE%
