@echo off
rem Runs Storykeeper using the private Python environment that setup.cmd made,
rem so there is nothing to "activate" and nothing to remember.
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%;%PYTHONPATH%"

if exist "%HERE%.venv\Scripts\python.exe" (
    "%HERE%.venv\Scripts\python.exe" -m storykeeper %*
    exit /b %errorlevel%
)

echo.
echo   Storykeeper has not been set up on this computer yet.
echo.
echo   Run  setup.cmd  in this folder first - it only takes a minute.
echo.
exit /b 1
