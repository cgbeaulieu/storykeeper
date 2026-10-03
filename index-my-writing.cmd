@echo off
rem ---------------------------------------------------------------------------
rem  Reads everything in the library folder so Storykeeper can search it.
rem  Run this again whenever you have written something new - it only looks
rem  at what changed, so it is quick after the first time.
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

echo.
echo   Reading your writing...
echo.
echo   The very first run also downloads the search model, about 130 MB.
echo   That happens once. After this it never goes online again.
echo.

call "%~dp0storykeeper.cmd" index

echo.
pause
