@echo off
REM ==========================================================================
REM  Seed Code - complete Windows build pipeline
REM    Stage 0: branding assets -> assets\windows\ (icon, wizard art, verinfo)
REM    Stage 1: PyInstaller     -> dist\seedcode.exe  (Seed Code icon embedded)
REM    Stage 2: Inno Setup      -> Release\SeedCodeSetup.exe
REM  Every stage is verified; the pipeline never reports success on a stale
REM  or unbranded artifact. No manual steps in between.
REM ==========================================================================
setlocal EnableDelayedExpansion

echo ============================================================
echo   Seed Code Build Pipeline (Windows)
echo ============================================================
echo.

REM --- Locate the repository root (two levels up from this script) ---------
set "REPO_ROOT=%~dp0..\.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
if not exist "%REPO_ROOT%\pyproject.toml" (
    echo [ERROR] Could not find pyproject.toml at "%REPO_ROOT%".
    exit /b 3
)
echo [INFO] Repository: %REPO_ROOT%

set "LOG_DIR=%USERPROFILE%\.seedcode\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
set "LOG_FILE=%LOG_DIR%\build.log"
echo [INFO] Log file:   %LOG_FILE%
echo ===== build.bat run: %DATE% %TIME% ===== >> "%LOG_FILE%"

REM --- Find a Python 3.12+ interpreter --------------------------------------
set "PY_CMD="
call :try_python py -3.13
if not defined PY_CMD call :try_python py -3.12
if not defined PY_CMD call :try_python py -3
if not defined PY_CMD call :try_python python
if not defined PY_CMD call :try_python python3
if not defined PY_CMD (
    echo [ERROR] Python 3.12+ is required to build. Run install.bat first.
    exit /b 2
)
echo [INFO] Using interpreter: %PY_CMD%

REM --- Read the source version once; every later stage checks against it ----
set "SRC_VERSION="
for /f "delims=" %%V in ('%PY_CMD% -c "import seedcode; print(seedcode.__version__)" 2^>nul') do set "SRC_VERSION=%%V"
if not defined SRC_VERSION (
    echo [ERROR] Could not read the source version from seedcode\__init__.py.
    echo         Run install.bat first so the seedcode package imports.
    exit /b 1
)
echo [INFO] Source version: v%SRC_VERSION%

REM ==========================================================================
REM  STAGE 0 - branding assets (icon, wizard bitmaps, exe version resource)
REM ==========================================================================
echo.
echo [STAGE 0/3] Generating branding assets...
%PY_CMD% "%~dp0build_assets.py" --version %SRC_VERSION% >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] Branding asset generation failed. See "%LOG_FILE%".
    exit /b 1
)
set "ICON=%REPO_ROOT%\assets\windows\seedcode.ico"
set "VERINFO=%REPO_ROOT%\assets\windows\version_info.txt"
if not exist "%ICON%" (
    echo [ERROR] assets\windows\seedcode.ico was not produced.
    exit /b 1
)
echo [OK] Stage 0 complete: Seed Code icon and wizard art verified.

REM ==========================================================================
REM  STAGE 1 - standalone executable (with the Seed Code icon embedded)
REM ==========================================================================
echo.
echo [STAGE 1/3] Building dist\seedcode.exe with PyInstaller...

%PY_CMD% -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [STEP] Installing PyInstaller...
    %PY_CMD% -m pip install --upgrade pyinstaller >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        echo [ERROR] Could not install PyInstaller. See "%LOG_FILE%".
        exit /b 1
    )
)
echo [STEP] Ensuring project dependencies are installed...
%PY_CMD% -m pip install -e "%REPO_ROOT%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. See "%LOG_FILE%".
    exit /b 1
)

REM --- Release gate: never package a build whose tests fail ------------------
%PY_CMD% -c "import pytest" >nul 2>&1
if errorlevel 1 (
    echo [STEP] Installing pytest ^(release gate^)...
    %PY_CMD% -m pip install pytest >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        echo [ERROR] Could not install pytest. See "%LOG_FILE%".
        exit /b 1
    )
)
echo [STEP] Running the test suite ^(release gate^)...
%PY_CMD% -m pytest "%REPO_ROOT%\tests" -q >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] The test suite FAILED - refusing to package a broken build.
    echo         See "%LOG_FILE%" for the failing tests.
    exit /b 1
)
echo [OK] All tests passed.

REM --- Clean previous outputs so nothing stale can survive into this build --
REM dist\ is deleted BEFORE building: if seedcode.exe exists after PyInstaller
REM runs, it was provably created by THIS run.
echo [STEP] Cleaning previous build outputs ^(build\, dist\, *.spec^)...
if exist "%REPO_ROOT%\build" rmdir /s /q "%REPO_ROOT%\build" >nul 2>&1
if exist "%REPO_ROOT%\dist" rmdir /s /q "%REPO_ROOT%\dist" >nul 2>&1
del /f /q "%REPO_ROOT%\*.spec" >nul 2>&1
del /f /q "%~dp0*.spec" >nul 2>&1
if exist "%REPO_ROOT%\dist\seedcode.exe" (
    echo [ERROR] Could not delete the old dist\seedcode.exe - it is locked.
    echo         Close every running Seed Code instance and re-run build.bat.
    exit /b 5
)
if exist "%REPO_ROOT%\build" (
    echo [ERROR] Could not delete the old build\ directory - files are locked.
    exit /b 5
)

REM --collect-all bundles rich/prompt_toolkit data files that static analysis
REM misses; build\ is a disposable work directory. --clean also purges the
REM PyInstaller cache so no previously-compiled module can leak in.
REM --icon + --version-file brand the exe: Explorer, taskbar, and every
REM shortcut resolve their icon from the exe's own resources, so the default
REM Python icon can never appear.
echo [STEP] Running PyInstaller ^(this can take a few minutes^)...
%PY_CMD% -m PyInstaller --noconfirm --clean --onefile --console ^
    --name seedcode ^
    --icon "%ICON%" ^
    --version-file "%VERINFO%" ^
    --distpath "%REPO_ROOT%\dist" ^
    --workpath "%REPO_ROOT%\build" ^
    --specpath "%REPO_ROOT%\build" ^
    --collect-all rich ^
    --collect-all prompt_toolkit ^
    --collect-submodules pydantic ^
    --collect-submodules openai ^
    "%REPO_ROOT%\seedcode\__main__.py" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed. See "%LOG_FILE%".
    exit /b 1
)
if not exist "%REPO_ROOT%\dist\seedcode.exe" (
    echo [ERROR] Build finished but dist\seedcode.exe is missing.
    exit /b 1
)

REM Sanity-check the freshly built exe AND prove it matches the source
REM version - an exe that merely runs could still be a stale binary.
echo [STEP] Verifying the executable against the source version...
"%REPO_ROOT%\dist\seedcode.exe" --version > "%TEMP%\seedcode-exe-version.txt" 2>nul
if errorlevel 1 (
    echo [ERROR] dist\seedcode.exe failed its --version smoke test.
    exit /b 1
)
set "EXE_VERSION="
for /f "usebackq delims=" %%V in ("%TEMP%\seedcode-exe-version.txt") do set "EXE_VERSION=%%V"
del /f /q "%TEMP%\seedcode-exe-version.txt" >nul 2>&1
echo [INFO] Source: v%SRC_VERSION%   Executable reports: "%EXE_VERSION%"
if /I not "%EXE_VERSION%"=="Seed Code v%SRC_VERSION%" (
    echo [ERROR] VERSION MISMATCH - the executable does not match the source.
    echo         Expected "Seed Code v%SRC_VERSION%". The build is stale or broken.
    exit /b 5
)

REM Prove the Seed Code icon really is inside the exe (not just requested).
echo [STEP] Verifying the executable embeds the Seed Code icon...
%PY_CMD% "%~dp0build_assets.py" --verify-exe "%REPO_ROOT%\dist\seedcode.exe"
if errorlevel 1 (
    echo [ERROR] The built exe does NOT contain the Seed Code icon.
    exit /b 5
)
echo [OK] Stage 1 complete: fresh, branded executable verified ^(v%SRC_VERSION%^).

REM ==========================================================================
REM  STAGE 2 - installer
REM ==========================================================================
echo.
echo [STAGE 2/3] Compiling Release\SeedCodeSetup.exe with Inno Setup...

REM Locate ISCC.exe: PATH first, then the standard install locations.
set "ISCC="
where iscc >nul 2>&1 && set "ISCC=iscc"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo [ERROR] Inno Setup 6 ^(ISCC.exe^) was not found.
    echo         Install it from https://jrsoftware.org/isdl.php and re-run.
    exit /b 4
)
echo [INFO] Using ISCC: %ISCC%

REM Delete the previous installer first: if SeedCodeSetup.exe exists after
REM ISCC runs, it was provably produced by THIS compile of THIS build.
if not exist "%REPO_ROOT%\Release" mkdir "%REPO_ROOT%\Release"
if exist "%REPO_ROOT%\Release\SeedCodeSetup.exe" del /f /q "%REPO_ROOT%\Release\SeedCodeSetup.exe" >nul 2>&1
if exist "%REPO_ROOT%\Release\SeedCodeSetup.exe" (
    echo [ERROR] Could not delete the old Release\SeedCodeSetup.exe - locked.
    exit /b 5
)

REM /DAppVersionFromBuild injects the verified source version, so the
REM installer metadata can never disagree with the executable it packages.
"%ISCC%" /DAppVersionFromBuild=%SRC_VERSION% /O"%REPO_ROOT%\Release" "%~dp0setup.iss" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [ERROR] Inno Setup compilation failed. See "%LOG_FILE%".
    exit /b 1
)
if not exist "%REPO_ROOT%\Release\SeedCodeSetup.exe" (
    echo [ERROR] ISCC succeeded but Release\SeedCodeSetup.exe is missing.
    exit /b 1
)

REM The installer must also carry the branding: its own icon resource comes
REM from SetupIconFile, so the same PNG payload must be present inside it.
echo [STEP] Verifying the installer embeds the Seed Code icon...
%PY_CMD% "%~dp0build_assets.py" --verify-exe "%REPO_ROOT%\Release\SeedCodeSetup.exe"
if errorlevel 1 (
    echo [ERROR] The installer does NOT contain the Seed Code icon.
    exit /b 5
)

echo.
echo ============================================================
echo   [SUCCESS] Build pipeline complete.
echo   Standalone exe : %REPO_ROOT%\dist\seedcode.exe
echo   Installer      : %REPO_ROOT%\Release\SeedCodeSetup.exe
echo   Both verified: correct version + Seed Code icon embedded.
echo ============================================================
echo [SUCCESS] pipeline complete >> "%LOG_FILE%"
exit /b 0

:try_python
"%1" %2 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 12) else 1)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=%1 %2"
exit /b 0
