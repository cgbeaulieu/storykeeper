@echo off
rem ---------------------------------------------------------------------------
rem  Opens Storykeeper so you can ask questions about your own book.
rem  Type a question, press Enter. Type  exit  when you are done.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Storykeeper has not been set up on this computer yet.
    echo   Double-click  setup.cmd  first.
    echo.
    pause
    exit /b 1
)

call "%~dp0storykeeper.cmd" chat

echo.
pause
