@echo off
setlocal
cd /d "%~dp0"

set "LAUNCHER=%~dp0TradeforAgentsLauncher.exe"
if not exist "%LAUNCHER%" (
  echo [launcher] TradeforAgentsLauncher.exe not found in %~dp0
  pause
  exit /b 1
)

"%LAUNCHER%" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [launcher] Start failed. Check ai_stock_sim\data\logs for details.
  pause
)
exit /b %EXIT_CODE%
