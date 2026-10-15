@echo off
setlocal
python "%~dp0tools\build.py" %*
exit /b %ERRORLEVEL%
