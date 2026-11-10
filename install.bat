@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Spoti-CL installer

set "REPO_DIR=%~dp0"
REM %~dp0 ends with a backslash, which would escape the closing quote when
REM the path is handed to pip. Keep both forms.
set "REPO_PATH=%REPO_DIR:~0,-1%"
set "INSTALL_DIR=%LOCALAPPDATA%\spoti-cl"
set "VENV_DIR=%INSTALL_DIR%\venv"
set "BIN_DIR=%INSTALL_DIR%\bin"
set "PY_CMD="
set "PY_LABEL="

echo.
echo   ==================================================
echo      Spoti-CL  -  Spotify links to high quality audio
echo   ==================================================
echo.

REM --------------------------------------------------------------- python ---
echo   [1/5] Looking for a working Python 3.10 or newer...

REM The py launcher, newest first. An interpreter that is broken (missing
REM DLLs, a half removed install) fails the import check and is skipped.
for %%V in (3.14 3.13 3.12 3.11 3.10 3) do call :try_python py -%%V
if not defined PY_CMD call :try_python py
if not defined PY_CMD call :try_python python
if not defined PY_CMD call :try_python python3

REM Standard install locations, including any that are not on PATH.
if not defined PY_CMD for /f "delims=" %%P in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\Python3*\python.exe" 2^>nul') do call :try_python "%%P"
if not defined PY_CMD for /f "delims=" %%P in ('dir /b /s "%ProgramFiles%\Python3*\python.exe" 2^>nul') do call :try_python "%%P"
if not defined PY_CMD for /f "delims=" %%P in ('dir /b /s "%APPDATA%\Roaming\uv\python\cpython-3*\python.exe" 2^>nul') do call :try_python "%%P"

if not defined PY_CMD (
    echo.
    echo   ERROR: no working Python 3.10+ was found.
    echo.
    echo   Install Python from https://www.python.org/downloads/
    echo   and tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)
echo         using %PY_CMD%  -  Python !PY_LABEL!

REM ----------------------------------------------------------------- venv ---
echo.
echo   [2/5] Creating the virtual environment...
set "NEED_VENV=1"
if exist "%VENV_DIR%\Scripts\python.exe" (
    "%VENV_DIR%\Scripts\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "NEED_VENV=0"
        echo         reusing %VENV_DIR%
    ) else (
        echo         the existing environment is broken, rebuilding it
        rmdir /s /q "%VENV_DIR%" >nul 2>&1
    )
)
if "%NEED_VENV%"=="1" (
    %PY_CMD% -m venv "%VENV_DIR%" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo   ERROR: could not create the virtual environment.
        echo   Run this by hand to see the error:
        echo       %PY_CMD% -m venv "%VENV_DIR%"
        echo.
        pause
        exit /b 1
    )
    echo         created %VENV_DIR%
)
set "VPY=%VENV_DIR%\Scripts\python.exe"
if not exist "%VPY%" (
    echo   ERROR: %VPY% is missing. Delete %INSTALL_DIR% and run this again.
    pause
    exit /b 1
)

REM ------------------------------------------------------------------ pip ---
echo.
echo   [3/5] Installing Spoti-CL...
"%VPY%" -m pip install --upgrade pip --quiet --disable-pip-version-check >nul 2>&1
if exist "%REPO_DIR%pyproject.toml" (
    echo         installing from the local checkout, editable
    "%VPY%" -m pip install -e "%REPO_PATH%" --quiet --disable-pip-version-check
) else (
    echo         installing from GitHub
    "%VPY%" -m pip install "git+https://github.com/Deepma1ya/Spoti-CL.git" --quiet --disable-pip-version-check
)
if errorlevel 1 (
    echo.
    echo   ERROR: the installation failed. The output above says why.
    echo.
    pause
    exit /b 1
)

REM --------------------------------------------------------------- shims ---
echo.
echo   [4/5] Creating the command shims...
if not exist "%BIN_DIR%" mkdir "%BIN_DIR%" >nul 2>&1

> "%BIN_DIR%\spoti-cl.cmd" echo @echo off
>> "%BIN_DIR%\spoti-cl.cmd" echo "%VPY%" -m spoti_cl %%*
>> "%BIN_DIR%\spoti-cl.cmd" echo exit /b %%ERRORLEVEL%%

> "%BIN_DIR%\spotidl.cmd" echo @echo off
>> "%BIN_DIR%\spotidl.cmd" echo "%VPY%" -m spoti_cl %%*
>> "%BIN_DIR%\spotidl.cmd" echo exit /b %%ERRORLEVEL%%

> "%BIN_DIR%\spoti-cl.ps1" echo ^& "%VPY%" -m spoti_cl @args; exit $LASTEXITCODE

echo         %BIN_DIR%\spoti-cl.cmd
echo         %BIN_DIR%\spotidl.cmd

REM ----------------------------------------------------------------- path ---
set "PATH_RESULT="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$b='%BIN_DIR%'; $p=[Environment]::GetEnvironmentVariable('Path','User'); if(-not $p){$p=''}; if($p -notlike ('*'+$b+'*')){[Environment]::SetEnvironmentVariable('Path',($p.TrimEnd(';')+';'+$b),'User');'ADDED'}else{'PRESENT'}" 2^>nul`) do set "PATH_RESULT=%%P"

REM --------------------------------------------------------------- verify ---
echo.
echo   [5/5] Checking the installation...
REM call is required, otherwise a batch file never returns to the caller.
call "%BIN_DIR%\spoti-cl.cmd" version >nul 2>&1
if errorlevel 1 (
    echo         WARNING: the shim did not run cleanly.
) else (
    echo         spoti-cl responds.
)

where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo.
    echo   NOTE: ffmpeg was not found on your PATH.
    echo         It is needed to convert to mp3 or flac. Install it with:
    echo.
    echo             winget install Gyan.FFmpeg
    echo.
    echo         Or download it from https://ffmpeg.org/download.html
    echo         and add its bin folder to your PATH.
) else (
    echo         ffmpeg found.
)

echo.
echo   ==================================================
echo    Done.
echo.
if "!PATH_RESULT!"=="ADDED" (
    echo    %BIN_DIR% was added to your user PATH.
    echo    Open a NEW terminal for it to take effect.
) else (
    echo    %BIN_DIR% is already on your PATH.
    echo    Open a NEW terminal if spoti-cl is not found.
)
echo.
echo    Then run:
echo.
echo        spoti-cl
echo.
echo    That opens the interactive shell. Paste a Spotify
echo    link and press enter to download it.
echo   ==================================================
echo.
pause
exit /b 0

REM ------------------------------------------------------------- subroutine ---
:try_python
if defined PY_CMD goto :eof
%* -c "import sys,ssl,socket,venv,ensurepip; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 goto :eof
set PY_CMD=%*
for /f "delims=" %%V in ('%* -c "import sys;print(str(sys.version_info[0])+chr(46)+str(sys.version_info[1]))" 2^>nul') do set "PY_LABEL=%%V"
goto :eof
