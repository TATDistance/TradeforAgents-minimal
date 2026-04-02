from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List, Mapping

from .settings import Settings, load_settings


class OpportunityPoolService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.path = self.settings.cache_dir / "opportunity_pool.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, object]:
        if not self.path.exists():
            return {"updated_at": "", "items": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"updated_at": "", "items": []}
        if not isinstance(payload, dict):
            return {"updated_at": "", "items": []}
        items = payload.get("items")
        if not isinstance(items, list):
            payload["items"] = []
        return payload

    def get_active(self, reference_time: datetime | None = None) -> List[Dict[str, object]]:
        now = reference_time or datetime.now()
        items = list(self.load().get("items") or [])
        active: List[Dict[str, object]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            expire_at = str(item.get("expire_at") or "")
            if expire_at:
                try:
                    if datetime.fromisoformat(expire_at) < now:
                        continue
                except Exception:
                    pass
            active.append(dict(item))
        active.sort(key=lambda row: (float(row.get("score") or 0.0), str(row.get("discovered_at") or "")), reverse=True)
        return active

    def update(
        self,
        candidates: List[Mapping[str, object]],
        *,
        source: str = "intraday_scan",
        reference_time: datetime | None = None,
        ttl_minutes: int | None = None,
    ) -> Dict[str, object]:
        now = reference_time or datetime.now()
        ttl = ttl_minutes or max(self.settings.watchlist_evolution.grace_period_minutes * 2, 120)
        active = {str(item.get("symbol") or ""): dict(item) for item in self.get_active(now) if str(item.get("symbol") or "")}
        added: List[str] = []
        refreshed: List[str] = []
        for candidate in candidates:
            symbol = str(candidate.get("symbol") or "").strip()
            if not symbol:
                continue
            payload = {
                "symbol": symbol,
                "score": float(candidate.get("score") or 0.0),
                "source": str(candidate.get("source") or source),
                "discovered_at": str(candidate.get("discovered_at") or now.isoformat(timespec="seconds")),
                "expire_at": str(candidate.get("expire_at") or (now + timedelta(minutes=ttl)).isoformat(timespec="seconds")),
                "reason": str(candidate.get("reason") or "盘中动态扫描发现新机会"),
            }
            if symbol in active:
                payload["discovered_at"] = str(active[symbol].get("discovered_at") or payload["discovered_at"])
                refreshed.append(symbol)
            else:
                added.append(symbol)
            active[symbol] = payload
        rows = sorted(active.values(), key=lambda item: (float(item.get("score") or 0.0), str(item.get("discovered_at") or "")), reverse=True)
        self.path.write_text(
            json.dumps({"updated_at": now.isoformat(timespec="seconds"), "items": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"updated_at": now.isoformat(timespec="seconds"), "items": rows, "added": added, "refreshed": refreshed}
