# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


WINDOWS_PACKAGING_ROOT = Path(globals().get("SPECPATH", Path.cwd())).resolve()
PROJECT_ROOT = WINDOWS_PACKAGING_ROOT.parents[1]


def collect_tree(root: Path, prefix: str):
    entries = []
    for path in root.rglob("*"):
        if path.is_file():
            relative_parent = path.relative_to(root).parent
            target_dir = Path(prefix) / relative_parent
            entries.append((str(path), str(target_dir).replace("\\", "/")))
    return entries

datas = []
datas += collect_data_files("streamlit", include_py_files=False)
datas += collect_tree(PROJECT_ROOT / "ai_stock_sim" / "config", "ai_stock_sim/config")
datas += collect_tree(PROJECT_ROOT / "ai_stock_sim" / "data" / "calendars", "ai_stock_sim/data/calendars")
datas += collect_tree(PROJECT_ROOT / "docs", "docs")
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
