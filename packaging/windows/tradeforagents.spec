# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_PACKAGING_ROOT = PROJECT_ROOT / "packaging" / "windows"

datas = []
datas += collect_data_files("streamlit", include_py_files=False)
datas += Tree(str(PROJECT_ROOT / "ai_stock_sim" / "config"), prefix="ai_stock_sim/config").toc
datas += Tree(str(PROJECT_ROOT / "ai_stock_sim" / "data" / "calendars"), prefix="ai_stock_sim/data/calendars").toc
datas += Tree(str(PROJECT_ROOT / "docs"), prefix="docs").toc
datas += [
    (str(PROJECT_ROOT / "README.md"), "."),
    (str(PROJECT_ROOT / ".env.example"), "."),
    (str(WINDOWS_PACKAGING_ROOT / "start.bat"), "."),
    (str(WINDOWS_PACKAGING_ROOT / "debug_console.bat"), "."),
    (str(WINDOWS_PACKAGING_ROOT / "launch_app.bat"), "."),
    (str(WINDOWS_PACKAGING_ROOT / "README_WINDOWS.txt"), "."),
]

hiddenimports = []
for package_name in (
    "ai_stock_sim",
    "ai_trade_system",
    "scripts",
    "app",
    "dashboard",
    "strategies",
    "streamlit",
    "uvicorn",
    "apscheduler",
    "akshare",
):
    hiddenimports += collect_submodules(package_name)

a = Analysis(
    [str(WINDOWS_PACKAGING_ROOT / "tradeforagents_launcher.py")],
    pathex=[str(PROJECT_ROOT), str(PROJECT_ROOT / "ai_stock_sim")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib.tests", "numpy.tests", "pandas.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TradeforAgentsLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TradeforAgentsLauncher",
)
