@echo off
rem ---------------------------------------------------------------------------
rem  Storykeeper - step 2 of the setup.
rem
rem  Double-click this AFTER setup.cmd has run and after Ollama is installed.
rem  It downloads the AI model that writes the answers - whichever one the
rem  settings name - then checks that every piece is talking to the others.
rem  It changes nothing else on the computer.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

echo.
echo   Storykeeper - finishing the setup
echo   =================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo   Storykeeper's own setup has not finished yet.
    echo.
    echo   Double-click  setup.cmd  in this folder first. When that says it is
    echo   done, come back and run this one.
    echo.
    pause
    exit /b 1
)

where ollama >nul 2>&1
if errorlevel 1 (
    echo   Ollama is not installed yet.
    echo.
    echo   That is the program that runs the AI on this computer - it is the
    echo   reason your writing never has to leave it.
    echo.
    echo     1. Go to  https://ollama.com  and install it.
    echo     2. Then double-click this file again.
    echo.
    pause
    exit /b 1
)

echo   Ollama is installed. Good.
echo.

rem Ask Storykeeper which model its settings name, so this file never has to
rem be edited when the model changes.
set "MODEL="
for /f "usebackq delims=" %%M in (`.venv\Scripts\python.exe -c "from storykeeper.config import load_config; print(load_config().llm.model)" 2^>nul`) do set "MODEL=%%M"

if not defined MODEL (
    echo   Storykeeper could not read its settings. Here is what it says:
    echo.
    call "%~dp0storykeeper.cmd" status
    echo.
    pause
    exit /b 1
)

echo   Now downloading the AI model, %MODEL%. This can be several
echo   gigabytes, it happens once, and it is the last big download. You can
echo   leave it running and go and do something else.
echo.

ollama pull %MODEL%
if errorlevel 1 (
    echo.
    echo   The download did not finish. The usual cause is the internet
    echo   dropping. Run this file again - it carries on from where it
    echo   stopped rather than starting over.
    echo.
    pause
    exit /b 1
)

echo.
echo   Model downloaded. Checking that everything is connected...
echo.

call "%~dp0storykeeper.cmd" status

echo.
echo   ==========================================================
echo    Setup is finished. Two things left, both yours:
echo.
echo      1. Put your writing into the "library" folder that is
echo         in this folder. There are subfolders already made
echo         for manuscript, characters, history, culture,
echo         locations and plot. Drop files into whichever fits.
echo         library\README.md explains what goes where.
echo.
echo      2. Double-click  index-my-writing.cmd
echo         Then double-click  ask-storykeeper.cmd
echo   ==========================================================
echo.
pause
