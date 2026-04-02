TradeforAgents-minimal Windows bundle
====================================

Quick start
-----------
1. Double-click start.bat
2. The launcher will open the TradeforAgents desktop window
3. If DEEPSEEK_API_KEY is missing, open the homepage settings panel and fill it in, or edit .env
4. Use debug_console.bat when you need engine + 8610 + console diagnostics

Files
-----
- TradeforAgentsLauncher.exe : bundled launcher executable
- start.bat                  : normal user entry
- debug_console.bat          : console diagnostics entry
- launch_app.bat             : generic wrapper

Important paths
---------------
- Homepage:  http://127.0.0.1:8600/
- Dashboard: http://127.0.0.1:8610/
- Logs:      ai_stock_sim\data\logs\
- Config:    .env

Notes
-----
- Python does not need to be installed separately.
- The installer defaults to a per-user directory so logs and SQLite files stay writable.
- If startup fails, check ai_stock_sim\data\logs and rerun debug_console.bat.
