@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHON=.runtime\python312\python.exe"
set "DENO_HOME=%CD%\.runtime\deno"
set "FFMPEG_HOME=%CD%\.runtime\ffmpeg\bin"

set "NEEDS_SETUP=0"
if not exist "%PYTHON%" set "NEEDS_SETUP=1"
if not exist "%DENO_HOME%\deno.exe" set "NEEDS_SETUP=1"
if not exist "%FFMPEG_HOME%\ffmpeg.exe" set "NEEDS_SETUP=1"
if not exist "%FFMPEG_HOME%\ffprobe.exe" set "NEEDS_SETUP=1"

rem The yt-dlp check is deliberate: an outdated copy still imports fine but
rem fails every download, which used to look like a broken app to the user.
if "%NEEDS_SETUP%"=="0" (
    "%PYTHON%" -c "import streamlit, pandas, yt_dlp, googleapiclient, google_auth_oauthlib, openai; assert tuple(map(int, openai.__version__.split('.')[:2])) >= (2, 44); assert tuple(int(''.join(filter(str.isdigit, p)) or 0) for p in yt_dlp.version.__version__.split('.')[:3]) >= (2026, 5, 1)" >nul 2>&1
    if errorlevel 1 set "NEEDS_SETUP=1"
)

if "%NEEDS_SETUP%"=="1" (
    echo Required tools are missing. Starting the automatic setup...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\setup.ps1"
    if errorlevel 1 (
        echo.
        echo Automatic setup failed. Check your internet connection and try again.
        pause
        exit /b 1
    )
)

set "PATH=%FFMPEG_HOME%;%DENO_HOME%;%PATH%"
start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://localhost:8501'"
"%PYTHON%" -m streamlit run app.py --server.headless=true --server.address=127.0.0.1 --server.port=8501 --browser.gatherUsageStats=false

if errorlevel 1 (
    echo.
    echo The app stopped with an error.
    pause
)
