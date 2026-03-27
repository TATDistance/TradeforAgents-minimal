from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_home() -> Path:
    return Path(__file__).resolve().parents[1]


def _workspace_root(home: Path) -> Path:
    resolved = home.resolve()
    if resolved.parent.name == "tools":
        return resolved.parent.parent
    return resolved.parent


def _default_tradeforagents_results_dir(home: Path, workspace_root: Path) -> Path:
    repo_root = home.parent
    embedded_results = repo_root / "results"
    if embedded_results.exists() and (repo_root / "scripts" / "minimal_web_app.py").exists():
        return embedded_results
    return workspace_root / "tools" / "TradeforAgents-minimal" / "results"


@dataclass(frozen=True)
class AppConfig:
    home: Path
    data_dir: Path
    reports_dir: Path
    db_path: Path
    tradeforagents_results_dir: Path
    vnpy_home: Path


def load_config() -> AppConfig:
    home = Path(os.environ.get("AI_TRADE_SYSTEM_HOME", str(_default_home()))).resolve()
    workspace_root = _workspace_root(home)
    data_dir = home / "data"
    reports_dir = home / "reports"
    db_path = Path(
        os.environ.get("AI_TRADE_DB_PATH", str(data_dir / "db.sqlite3"))
    ).resolve()
    tradeforagents_results_dir = Path(
        os.environ.get(
            "TRADEFORAGENTS_RESULTS_DIR",
            str(_default_tradeforagents_results_dir(home, workspace_root)),
        )
    ).resolve()
    vnpy_home = Path(
        os.environ.get(
            "VN_PY_HOME",
            str(workspace_root / "tools" / "vnpy-4.3.0" / "vnpy-4.3.0"),
        )
    ).resolve()

    return AppConfig(
        home=home,
        data_dir=data_dir,
        reports_dir=reports_dir,
        db_path=db_path,
        tradeforagents_results_dir=tradeforagents_results_dir,
        vnpy_home=vnpy_home,
    )
