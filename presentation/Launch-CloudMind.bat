@echo off
setlocal
title CloudMind 3D Presentation
where.exe node.exe >nul 2>&1
if errorlevel 1 (
    echo Node.js was not found on PATH. Install Node.js 20 or newer and reopen this launcher.
    goto failed
)
node.exe "%~dp0launch-cloudmind.mjs"
if not errorlevel 1 exit /b 0

:failed
echo.
echo CloudMind could not start.
pause
exit /b 1
