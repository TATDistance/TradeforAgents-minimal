from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Iterable


WEB_HOST = "127.0.0.1"
WEB_PORT = 8600
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8610


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[2]


def _launch_command(role: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), role]
    return [str(Path(sys.executable).resolve()), str(Path(__file__).resolve()), role]


def _prepare_sys_path(bundle_root: Path) -> None:
    for path in (bundle_root, bundle_root / "ai_stock_sim"):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def _runtime_paths(bundle_root: Path) -> dict[str, Path]:
    ai_stock_sim_root = bundle_root / "ai_stock_sim"
    return {
        "bundle_root": bundle_root,
        "logs_dir": ai_stock_sim_root / "data" / "logs",
        "cache_dir": ai_stock_sim_root / "data" / "cache",
        "reports_dir": ai_stock_sim_root / "data" / "reports",
        "accounts_dir": ai_stock_sim_root / "data" / "accounts",
        "results_dir": bundle_root / "results",
        "env_file": bundle_root / ".env",
        "env_example": bundle_root / ".env.example",
    }


def _ensure_runtime_layout(bundle_root: Path) -> dict[str, Path]:
    paths = _runtime_paths(bundle_root)
    for key in ("logs_dir", "cache_dir", "reports_dir", "accounts_dir", "results_dir"):
        paths[key].mkdir(parents=True, exist_ok=True)
    for report_name in ("daily", "weekly", "monthly", "backtest"):
        (paths["reports_dir"] / report_name).mkdir(parents=True, exist_ok=True)
    if not paths["env_file"].exists() and paths["env_example"].exists():
        shutil.copyfile(paths["env_example"], paths["env_file"])
    return paths


def _configure_env(bundle_root: Path) -> dict[str, str]:
    _ensure_runtime_layout(bundle_root)
    env = os.environ.copy()
    env.setdefault("MINIMAL_WEB_HOST", WEB_HOST)
    env.setdefault("MINIMAL_WEB_PORT", str(WEB_PORT))
    env.setdefault("NO_PROXY", "127.0.0.1,localhost")
    env.setdefault("no_proxy", "127.0.0.1,localhost")
    env.setdefault("AI_TRADE_SYSTEM_HOME", str(bundle_root / "ai_trade_system"))
    env.setdefault("AI_STOCK_SIM_SETTINGS", str(bundle_root / "ai_stock_sim" / "config" / "settings.yaml"))
    return env


def _read_env_value(env_file: Path, key: str) -> str:
    if not env_file.exists():
        return ""
    try:
        for raw in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if raw.startswith(f"{key}="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return ""
    return ""


def _api_key_configured(bundle_root: Path) -> bool:
    paths = _runtime_paths(bundle_root)
    if os.environ.get("DEEPSEEK_API_KEY", "").strip():
        return True
    return bool(_read_env_value(paths["env_file"], "DEEPSEEK_API_KEY"))


def _port_open(host: str, port: int) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        try:
            return sock.connect_ex((host, port)) == 0
        finally:
            sock.close()
    except OSError:
        return False


def _wait_for_port(host: str, port: int, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _port_open(host, port):
            return True
        time.sleep(0.5)
    return False


def _log_file(bundle_root: Path, role: str) -> Path:
    return _runtime_paths(bundle_root)["logs_dir"] / f"{role}_launcher.log"


def _launch_detached(bundle_root: Path, role: str, *, console: bool = False) -> subprocess.Popen[bytes]:
    env = _configure_env(bundle_root)
    command = _launch_command(role)
    kwargs: dict[str, object] = {
        "cwd": str(bundle_root),
        "env": env,
        "close_fds": False,
    }
    if os.name == "nt" and not console:
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    if console:
        return subprocess.Popen(command, **kwargs)
    log_path = _log_file(bundle_root, role)
    handle = open(log_path, "a", encoding="utf-8")
    try:
        return subprocess.Popen(command, stdout=handle, stderr=handle, **kwargs)
    finally:
        handle.close()


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception:
        pass


def _print_runtime_status(bundle_root: Path) -> None:
    paths = _runtime_paths(bundle_root)
    print(f"[launcher] project root: {bundle_root}")
    print(f"[launcher] logs dir: {paths['logs_dir']}")
    print(f"[launcher] env file: {paths['env_file']}")
    print(f"[launcher] 8600 url: http://{WEB_HOST}:{WEB_PORT}/")
    print(f"[launcher] 8610 url: http://{DASHBOARD_HOST}:{DASHBOARD_PORT}/")


def _launch_main(engine: bool, dashboard: bool, no_browser: bool, console: bool, timeout_seconds: int) -> int:
    bundle_root = _bundle_root()
    _prepare_sys_path(bundle_root)
    _configure_env(bundle_root)
    _print_runtime_status(bundle_root)

    if not _port_open(WEB_HOST, WEB_PORT):
        print("[launcher] starting 8600 homepage...")
        _launch_detached(bundle_root, "web", console=console)
    else:
        print("[launcher] 8600 already running on port 8600")

    if not _wait_for_port(WEB_HOST, WEB_PORT, timeout_seconds):
        print(f"[launcher] 8600 failed to open within {timeout_seconds}s")
        return 1

    if engine:
        print("[launcher] starting realtime engine...")
        _launch_detached(bundle_root, "engine", console=console)

    if dashboard:
        if not _port_open(DASHBOARD_HOST, DASHBOARD_PORT):
            print("[launcher] starting 8610 dashboard...")
            _launch_detached(bundle_root, "dashboard", console=console)
        else:
            print("[launcher] 8610 already running on port 8610")
        if not _wait_for_port(DASHBOARD_HOST, DASHBOARD_PORT, timeout_seconds):
            print(f"[launcher] 8610 failed to open within {timeout_seconds}s")
            return 1

    if not _api_key_configured(bundle_root):
        print("[launcher] DEEPSEEK_API_KEY not found. Open 8600 and fill the homepage settings panel or edit .env.")

    if not no_browser:
        _open_browser(f"http://{WEB_HOST}:{WEB_PORT}/")

    print("[launcher] launch finished")
    return 0


def _run_web() -> int:
    bundle_root = _bundle_root()
    _prepare_sys_path(bundle_root)
    _configure_env(bundle_root)
    from scripts.minimal_web_app import app  # noqa: WPS433
    import uvicorn  # noqa: WPS433

    uvicorn.run(
        app,
        host=os.getenv("MINIMAL_WEB_HOST", WEB_HOST),
        port=int(os.getenv("MINIMAL_WEB_PORT", str(WEB_PORT))),
        reload=False,
    )
    return 0


def _run_engine() -> int:
    bundle_root = _bundle_root()
    _prepare_sys_path(bundle_root)
    _configure_env(bundle_root)
    from app.main import main  # noqa: WPS433

    return int(main())


def _run_dashboard() -> int:
    bundle_root = _bundle_root()
    _prepare_sys_path(bundle_root)
    _configure_env(bundle_root)
    streamlit_home = bundle_root / "ai_stock_sim" / ".streamlit_home"
    streamlit_config_dir = streamlit_home / ".streamlit"
    streamlit_config_dir.mkdir(parents=True, exist_ok=True)
    (streamlit_config_dir / "config.toml").write_text(
        "[browser]\n"
        "gatherUsageStats = false\n\n"
        "[server]\n"
        "headless = true\n",
        encoding="utf-8",
    )
    (streamlit_config_dir / "credentials.toml").write_text(
        "[general]\nemail = \"\"\n",
        encoding="utf-8",
    )
    os.environ["HOME"] = str(streamlit_home)
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    from streamlit.web import cli as stcli  # noqa: WPS433

    script_path = bundle_root / "ai_stock_sim" / "dashboard" / "dashboard_app.py"
    sys.argv = [
        "streamlit",
        "run",
        str(script_path),
        "--server.port",
        str(DASHBOARD_PORT),
        "--server.address",
        "0.0.0.0",
        "--browser.gatherUsageStats",
        "false",
    ]
    stcli.main()
    return 0


def _check_status(ports: Iterable[tuple[str, int]]) -> int:
    for name, port in ports:
        status = "running" if _port_open("127.0.0.1", port) else "stopped"
        print(f"{name}: {status} ({port})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TradeforAgents Windows launcher")
    subparsers = parser.add_subparsers(dest="command")

    launch = subparsers.add_parser("launch", help="Start 8600 and optional services")
    launch.add_argument("--engine", action="store_true", help="Also start realtime engine")
    launch.add_argument("--dashboard", action="store_true", help="Also start 8610 dashboard")
    launch.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    launch.add_argument("--console", action="store_true", help="Keep child processes attached to current console")
    launch.add_argument("--timeout", type=int, default=25, help="Startup timeout in seconds")

    subparsers.add_parser("web", help="Run 8600 web service in foreground")
    subparsers.add_parser("engine", help="Run realtime engine in foreground")
    subparsers.add_parser("dashboard", help="Run 8610 dashboard in foreground")
    subparsers.add_parser("status", help="Show current port status")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "launch"

    if command == "launch":
        return _launch_main(
            engine=bool(args.engine),
            dashboard=bool(args.dashboard),
            no_browser=bool(args.no_browser),
            console=bool(args.console),
            timeout_seconds=int(args.timeout),
        )
    if command == "web":
        return _run_web()
    if command == "engine":
        return _run_engine()
    if command == "dashboard":
        return _run_dashboard()
    if command == "status":
        return _check_status((("web", WEB_PORT), ("dashboard", DASHBOARD_PORT)))
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
