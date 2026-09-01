from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def latest_screening_rows() -> List[Dict[str, Any]]:
    folder = PROJECT_ROOT / "batch_results"
    if not folder.exists():
        return []
    files = sorted(folder.glob("stock_screening_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return []
    try:
        payload = json.loads(files[0].read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "results", "rows", "stocks", "top", "items", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    for value in payload.values():
        if isinstance(value, list) and any(isinstance(x, dict) and ("symbol" in x or "ticker" in x) for x in value[:5]):
            return [x for x in value if isinstance(x, dict)]
    return []


def latest_screening_row(symbol: str) -> Optional[Dict[str, Any]]:
    symbol = symbol.upper().strip()
    for row in latest_screening_rows():
        code = str(row.get("symbol") or row.get("ticker") or row.get("code") or "").upper().strip()
        if code == symbol:
            return row
    return None
