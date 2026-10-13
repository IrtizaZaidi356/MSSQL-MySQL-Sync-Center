@echo off
setlocal
cd /d "%~dp0"
python main.py
if errorlevel 1 (
    echo.
    echo The Sync Manager could not start. Check Python and the installation instructions.
    pause
)
endlocal
