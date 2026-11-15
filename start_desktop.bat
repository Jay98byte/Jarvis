@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [X] Jarvis is not installed yet. Run install.bat first.
    pause
    exit /b 1
)

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "jarvis_desktop.py"
) else (
    ".venv\Scripts\python.exe" "jarvis_desktop.py"
    if errorlevel 1 (
        echo.
        echo [X] Jarvis stopped because of an error.
        pause
    )
)
