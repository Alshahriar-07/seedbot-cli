@echo off
REM ==========================================================================
REM  Seed Code - Windows uninstaller
REM    1. Remove Seed Code entries from the user PATH (if any)
REM    2. Uninstall the Python package
REM    3. Remove user data (~\.seedcode) only after explicit confirmation
REM  Usage:  uninstall.bat            (interactive)
REM          uninstall.bat /keepdata  (never touch user data)
REM ==========================================================================
setlocal EnableDelayedExpansion

echo ============================================================
echo   Seed Code Uninstaller (Windows)
echo ============================================================
echo.

REM --- 1. PATH cleanup (per-user PATH stored in HKCU\Environment) -----------
REM PowerShell handles the string surgery reliably; only entries containing
REM "seedcode" are removed, everything else is preserved verbatim.
echo [STEP] Checking user PATH for Seed Code entries...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=[Environment]::GetEnvironmentVariable('Path','User'); if($p){ $parts=$p -split ';' | Where-Object {$_ -ne ''}; $kept=$parts | Where-Object {$_ -notmatch 'seedcode'}; if($kept.Count -ne $parts.Count){ [Environment]::SetEnvironmentVariable('Path', ($kept -join ';'), 'User'); Write-Host '[OK] Removed Seed Code entries from the user PATH.' } else { Write-Host '[INFO] No Seed Code entries on the user PATH.' } } else { Write-Host '[INFO] User PATH is empty.' }"
if errorlevel 1 echo [WARN] PATH cleanup could not be completed.

REM --- 2. Uninstall the Python package ---------------------------------------
echo.
echo [STEP] Uninstalling the Seed Code Python package...
set "PY_CMD="
call :try_python py -3
if not defined PY_CMD call :try_python python
if not defined PY_CMD call :try_python python3
if defined PY_CMD (
    %PY_CMD% -m pip uninstall -y seedcode
    if errorlevel 1 (
        echo [INFO] pip reported nothing to remove ^(package already gone^).
    ) else (
        echo [OK] Python package removed.
    )
) else (
    echo [WARN] No Python interpreter found - skipping pip uninstall.
)

REM --- 3. User data (confirmation required) ----------------------------------
echo.
if /I "%~1"=="/keepdata" (
    echo [INFO] Keeping user data at "%USERPROFILE%\.seedcode" ^(/keepdata^).
    goto :done
)
if not exist "%USERPROFILE%\.seedcode" (
    echo [INFO] No user data directory to remove.
    goto :done
)
echo The folder "%USERPROFILE%\.seedcode" holds your settings, API keys,
echo chat history, and logs.
set /p CONFIRM="Delete it too? [y/N] "
if /I "!CONFIRM!"=="y" (
    rmdir /s /q "%USERPROFILE%\.seedcode"
    echo [OK] User data deleted.
) else (
    echo [INFO] User data preserved.
)

:done
echo.
echo ============================================================
echo   [DONE] Seed Code has been removed.
echo   Open a NEW terminal so the PATH change takes effect.
echo ============================================================
exit /b 0

:try_python
"%1" %2 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY_CMD=%1 %2"
exit /b 0
