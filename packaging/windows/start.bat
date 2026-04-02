@echo off
setlocal
cd /d "%~dp0"

echo TradeforAgents Windows launcher
echo.
echo This launcher will open the TradeforAgents desktop window.
echo.

set "ENGINE_ARG="
set "DASHBOARD_ARG="

choice /C YN /N /M "Also start realtime engine? [Y/N]: "
if errorlevel 2 goto skip_engine
set "ENGINE_ARG=--engine"
:skip_engine

choice /C YN /N /M "Also open 8610 dashboard? [Y/N]: "
if errorlevel 2 goto skip_dashboard
set "DASHBOARD_ARG=--dashboard"
:skip_dashboard

call "%~dp0launch_app.bat" launch %ENGINE_ARG% %DASHBOARD_ARG%
exit /b %ERRORLEVEL%
