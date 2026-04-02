@echo off
setlocal
cd /d "%~dp0"

echo TradeforAgents debug console
echo 8600 + realtime engine + 8610 will be started in console mode.
echo.

call "%~dp0launch_app.bat" launch --engine --dashboard --console
echo.
echo Launcher finished. Logs are under ai_stock_sim\data\logs
pause
