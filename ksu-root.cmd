@echo off
setlocal
chcp 65001 >nul
title KSU Toolbox
set "KSU_FROM_CMD=1"
if exist "%~dp0ksu-root.exe" goto binary
python "%~dp0src\cli.py" %*
goto finished
:binary
"%~dp0ksu-root.exe" %*
:finished
set "KSU_EXIT=%ERRORLEVEL%"
if "%KSU_EXIT%"=="0" if "%~1"=="" exit /b 0
echo.
echo [KernelSU Tool] Exit code: %KSU_EXIT%
if not "%KSU_NO_PAUSE%"=="1" pause
exit /b %KSU_EXIT%
