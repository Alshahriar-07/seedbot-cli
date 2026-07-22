@echo off
REM ==========================================================================
REM  Seed Code - Windows installer
REM    1. Verify Python 3.12+ is available (open python.org if missing)
REM    2. Upgrade pip
REM    3. Install dependencies from requirements.txt
REM    4. Install Seed Code in editable mode
REM    5. Verify the installation
REM  Run from anywhere; the script locates the repository relative to itself.
REM ==========================================================================
setlocal EnableDelayedExpansion

echo ============================================================
echo   Seed Code Installer (Windows)
echo ============================================================
echo.

REM --- Locate the repository root (two levels up from this script) ---------
set "REPO_ROOT=%~dp0..\.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
if not exist "%REPO_ROOT%\pyproject.toml" (
    echo [ERROR] Could not find pyproject.toml at "%REPO_ROOT%".
    echo         Keep this script inside the repository: scripts\windows\install.bat
    exit /b 3
)
echo [INFO] Repository: %REPO_ROOT%

REM --- Log everything to a file as well as the console ----------------------
set "LOG_DIR=%USERPROFILE%\.seedcode\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
set "LOG_FILE=%LOG_DIR%\install.log"
echo [INFO] Log file:   %LOG_FILE%
echo ===== install.bat run: %DATE% %TIME% ===== >> "%LOG_FILE%"

REM --- 1. Find a Python 3.12+ interpreter ----------------------------------
REM Try the Windows launcher with explicit versions first, then generic names.
set "PY_CMD="
call :try_python py -3.13
if not defined PY_CMD call :try_python py -3.12
if not defined PY_CMD call :try_python py -3
if not defined PY_CMD call :try_python python
if not defined PY_CMD call :try_python python3

if not defined PY_CMD (
    echo.
    echo [ERROR] Python 3.12 or newer was not found on this system.
    echo [INFO]  Opening the official Python download page...
    start "" "https://www.python.org/downloads/"
    echo.
    echo Install Python 3.12+ ^(check "Add python.exe to PATH"^) and re-run this script.
    echo [FAILED] Python 3.12+ missing. >> "%LOG_FILE%"
    exit /b 2
)
echo [INFO] Using interpreter: %PY_CMD%

REM --- 2. Upgrade pip --------------------------------------------------------
echo.
echo [STEP] Upgrading pip...
%PY_CMD% -m pip install --upgrade pip >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] pip upgrade failed. Common causes:
    echo         - no internet connection ^(check and retry^)
    echo         - permission denied ^(re-run from an Administrator prompt, or
    echo           use:  %PY_CMD% -m pip install --user --upgrade pip^)
    echo         Details: "%LOG_FILE%"
    exit /b 1
)

REM --- 3. Install dependencies ----------------------------------------------
if exist "%REPO_ROOT%\requirements.txt" (
    echo [STEP] Installing dependencies from requirements.txt...
    %PY_CMD% -m pip install -r "%REPO_ROOT%\requirements.txt" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. See "%LOG_FILE%".
        exit /b 1
    )
) else (
    echo [WARN] requirements.txt not found - relying on pyproject dependencies.
)

REM --- 4. Install Seed Code in editable mode ---------------------------------
echo [STEP] Installing Seed Code ^(editable^)...
%PY_CMD% -m pip install -e "%REPO_ROOT%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] Seed Code installation failed. See "%LOG_FILE%".
    exit /b 1
)

REM --- 5. Verify ---------------------------------------------------------------
REM Primary check: the console script. Fallback: python -m seedcode. One of
REM the two MUST answer with the version, or the install is reported failed.
echo [STEP] Verifying installation...
set "VERIFIED="
seedcode --version >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%V in ('seedcode --version') do echo [OK] %%V ^(seedcode command works^)
    set "VERIFIED=1"
) else (
    %PY_CMD% -m seedcode --version >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%V in ('%PY_CMD% -m seedcode --version') do echo [OK] %%V ^(via python -m seedcode^)
        set "VERIFIED=1"
    )
)
if not defined VERIFIED (
    echo [ERROR] Verification failed: neither 'seedcode --version' nor
    echo         '%PY_CMD% -m seedcode --version' answered.
    echo         The install did not complete - see "%LOG_FILE%".
    echo [FAILED] verification >> "%LOG_FILE%"
    exit /b 1
)
where seedcode >nul 2>&1
if errorlevel 1 (
    echo [WARN] 'seedcode' is not on PATH in THIS terminal.
    echo        Open a NEW terminal and try:  seedcode
    echo        If it is still missing, ensure your Python Scripts folder is on
    echo        PATH ^(re-run the python.org installer and tick "Add to PATH"^),
    echo        or always launch with:  %PY_CMD% -m seedcode
) else (
    for /f "delims=" %%P in ('where seedcode') do echo [OK] seedcode command: %%P
)

echo.
echo ============================================================
echo   [SUCCESS] Seed Code is installed. Run:  seedcode
echo ============================================================
echo [SUCCESS] install complete >> "%LOG_FILE%"
exit /b 0

REM --- helper: set PY_CMD if the candidate is Python 3.12+ -------------------
:try_python
"%1" %2 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 12) else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=%1 %2"
exit /b 0
