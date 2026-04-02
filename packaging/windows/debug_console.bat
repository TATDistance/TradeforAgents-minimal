@echo off
setlocal
cd /d "%~dp0"

echo TradeforAgents debug console
echo 8600 + realtime engine + 8610 will be started in console mode.
echo.

set "LAUNCHER=%~dp0TradeforAgentsLauncherDebug.exe"
if not exist "%LAUNCHER%" set "LAUNCHER=%~dp0TradeforAgentsLauncher.exe"

"%LAUNCHER%" launch --engine --dashboard --console
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Launcher finished. Logs are under ai_stock_sim\data\logs
pause
exit /b %EXIT_CODE%
