@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Spoti-CL uninstaller

set "INSTALL_DIR=%LOCALAPPDATA%\spoti-cl"
set "BIN_DIR=%INSTALL_DIR%\bin"
set "VENV_DIR=%INSTALL_DIR%\venv"

echo.
echo   ==================================================
echo      Spoti-CL uninstaller
echo   ==================================================
echo.

if not exist "%INSTALL_DIR%" (
    echo   Nothing to remove - %INSTALL_DIR% does not exist.
    echo.
    pause
    exit /b 0
)

echo   Removing the command shims...
if exist "%BIN_DIR%" del /q "%BIN_DIR%\spoti-cl.cmd" "%BIN_DIR%\spotidl.cmd" "%BIN_DIR%\spoti-cl.ps1" >nul 2>&1

echo   Removing the virtual environment...
if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%" >nul 2>&1

echo   Removing the cache and history...
if exist "%INSTALL_DIR%\cache" rmdir /s /q "%INSTALL_DIR%\cache" >nul 2>&1
if exist "%INSTALL_DIR%\history" del /q "%INSTALL_DIR%\history" >nul 2>&1

echo   Taking %BIN_DIR% back off your PATH...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$b='%BIN_DIR%'; $p=[Environment]::GetEnvironmentVariable('Path','User'); if($p){$parts=$p -split ';' | Where-Object { $_ -and $_.Trim() -ne $b }; [Environment]::SetEnvironmentVariable('Path',($parts -join ';'),'User')}" >nul 2>&1

if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%" >nul 2>&1

echo.
echo   ==================================================
echo    Spoti-CL has been removed.
echo.
echo    Open a NEW terminal for the PATH change to apply.
echo   ==================================================
echo.
pause
exit /b 0
