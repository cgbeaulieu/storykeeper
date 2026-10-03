@echo off
rem ---------------------------------------------------------------------------
rem  Storykeeper setup for Windows.
rem
rem  Double-click this file, or run it from a Command Prompt. It creates a
rem  private Python environment inside this folder and installs the four
rem  packages Storykeeper needs. It does not change anything else on your
rem  computer, and it does not touch your writing.
rem ---------------------------------------------------------------------------
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo   Storykeeper setup
echo   =================
echo.

rem --- 1. Find a Python that is new enough ------------------------------------

set "PY="
for %%C in ("py -3" "python" "python3") do (
    if not defined PY (
        %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
        if !errorlevel! equ 0 set "PY=%%~C"
    )
)

if not defined PY (
    echo   PROBLEM: Python 3.11 or newer was not found on this computer.
    echo.
    echo   What to do:
    echo     1. Go to  https://www.python.org/downloads/
    echo     2. Download the latest version for Windows and run the installer.
    echo     3. IMPORTANT: on the first screen of the installer, tick the box
    echo        that says "Add python.exe to PATH" before clicking Install.
    echo     4. Close this window, open a new one, and run setup.cmd again.
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%V in ('%PY% -c "import sys;print(sys.version.split()[0])"') do set "PYVER=%%V"
echo   Found Python %PYVER%.
echo.

rem --- 2. Create the private environment ---------------------------------------

if exist ".venv\Scripts\python.exe" (
    echo   Using the Python environment that is already here.
) else (
    echo   Creating a private Python environment in .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo.
        echo   PROBLEM: the environment could not be created.
        echo   Try running setup.cmd again. If it keeps failing, reinstall
        echo   Python from https://www.python.org/downloads/ and tick
        echo   "Add python.exe to PATH".
        echo.
        pause
        exit /b 1
    )
)

set "VPY=%CD%\.venv\Scripts\python.exe"

rem --- 3. Install what Storykeeper needs ---------------------------------------

echo.
echo   Installing the pieces Storykeeper needs. This takes a minute or two
echo   and needs the internet, but only this once.
echo.

"%VPY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%VPY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo   PROBLEM: the installation did not finish.
    echo   The usual cause is no internet connection. Check that, then run
    echo   setup.cmd again.
    echo.
    pause
    exit /b 1
)

rem --- 4. Make the library folders ---------------------------------------------

for %%D in (manuscript characters history culture locations plot other) do (
    if not exist "library\%%D" mkdir "library\%%D"
)

rem --- 5. Say what is left to do ------------------------------------------------

echo.
echo   ==========================================================
echo   Setup is done.
echo   ==========================================================
echo.

where ollama >nul 2>&1
if errorlevel 1 (
    echo   STILL TO DO - install Ollama, which runs the AI on this computer:
    echo.
    echo     1. Go to  https://ollama.com  and install it.
    echo     2. Then double-click  finish-setup.cmd  in this folder.
    echo.
) else (
    echo   NEXT: double-click  finish-setup.cmd  in this folder. It downloads
    echo   the AI model and checks that everything is connected.
    echo.
)

echo   THEN:
echo.
echo     1. Put your writing in the "library" folder, in the subfolders
echo        that are now there. See library\README.md.
echo.
echo     2. Double-click  index-my-writing.cmd  to read it in, then
echo        ask-storykeeper.cmd  to start asking questions.
echo.
echo        Or, from a terminal in this folder:
echo.
echo            .\storykeeper index
echo            .\storykeeper chat
echo.
echo        ^(Type the  .\  at the front - it tells Windows to look in
echo         this folder.^)
echo.
pause
