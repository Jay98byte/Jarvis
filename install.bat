@echo off
REM ==============================================================================
REM  JARVIS AI PERSONAL ASSISTANT - 1-CLICK WINDOWS SETUP SCRIPT
REM ==============================================================================

setlocal enabledelayedexpansion

echo.
echo ==================================================================
echo           WELCOME TO JARVIS AI ASSISTANT SETUP
echo ==================================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python is NOT installed or not in PATH
    echo.
    echo Please install Python 3.10+ from: https://python.org
    echo.
    echo IMPORTANT: During installation, CHECK the box:
    echo "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

echo [OK] Python detected successfully!
echo.

REM Create virtual environment if it doesn't exist
if not exist ".venv" (
    echo [*] Creating virtual environment: .venv...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [X] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created!
    echo.
) else (
    echo [OK] Virtual environment already exists!
    echo.
)

REM Activate virtual environment
echo [*] Activating virtual environment...
call .venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [X] Failed to activate virtual environment
    pause
    exit /b 1
)
echo [OK] Virtual environment activated!
echo.

REM Upgrade pip
echo [*] Upgrading pip...
python -m pip install --upgrade pip
if %errorlevel% neq 0 (
    echo [!] Warning: pip upgrade had issues, continuing anyway...
)
echo.

REM Install requirements
echo [*] Installing dependencies from requirements.txt...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [X] Failed to install requirements
    echo.
    echo Try running manually:
    echo   1. Open Command Prompt in this folder
    echo   2. Run: .venv\Scripts\activate.bat
    echo   3. Run: pip install -r requirements.txt
    pause
    exit /b 1
)
echo [OK] Dependencies installed!
echo.

REM Install speech output; sounddevice voice input is installed from requirements.txt
echo [*] Installing speech output package (pyttsx3)...
pip install pyttsx3
if %errorlevel% neq 0 (
    echo [!] Warning: speech output package could not be installed
)
echo [OK] Voice input uses sounddevice and does not require PyAudio.
echo.

REM Create a Desktop shortcut for future launches
echo [*] Creating Jarvis Desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'Jarvis AI.lnk')); $shortcut.TargetPath = Join-Path '%~dp0' 'start_jarvis.bat'; $shortcut.WorkingDirectory = '%~dp0'; $shortcut.Description = 'Start Jarvis AI Workplace'; $shortcut.Save()"
if errorlevel 1 (
    echo [!] Could not create the Desktop shortcut. You can run start_workplace.bat directly.
)
echo.

REM Setup complete
echo.
echo ==================================================================
echo [+] JARVIS SETUP COMPLETED SUCCESSFULLY!
echo ==================================================================
echo.
echo NEXT STEPS:
echo.
echo 1. Get your FREE Groq API key:
echo    Visit: https://console.groq.com/keys
echo.
echo 2. To start Jarvis Workplace, double-click the Jarvis AI Desktop shortcut
echo    or run start_workplace.bat
echo.
echo 3. Allow microphone access in Windows when prompted. Workplace settings
echo    are saved in that browser; your existing Groq key stays local to Jarvis.
echo.
pause

REM Start Jarvis
echo.
echo [*] Starting Jarvis AI Assistant...
echo.
call "%~dp0start_workplace.bat"
