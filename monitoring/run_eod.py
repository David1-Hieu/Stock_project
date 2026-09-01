"""Run one end-of-day monitoring cycle.

Usage:
    python -m monitoring.run_eod
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from database import get_watchlist, save_recommendation
from monitoring.daily_snapshot import BENCHMARKS, capture_symbol
from monitoring.five_day_analyzer import analyze_symbol
from recommendation.engine import recommend

LOGGER = logging.getLogger("run_eod")


def run_once() -> Dict[str, Any]:
    watchlist = [x["symbol"] for x in get_watchlist() if x.get("status") == "ACTIVE"]
    captures: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for symbol in [*BENCHMARKS, *watchlist]:
        try:
            captures.append(capture_symbol(symbol, is_benchmark=symbol in BENCHMARKS))
        except Exception as exc:
            LOGGER.exception("Không capture được %s", symbol)
            errors.append({"symbol": symbol, "error": str(exc)})

    recommendations = []
    for symbol in watchlist:
        analysis = analyze_symbol(symbol, sessions=5)
        if analysis.get("success"):
            rec = recommend(analysis)
            save_recommendation(rec)
            recommendations.append(rec)

    return {
        "success": not bool(errors),
        "watchlist_count": len(watchlist),
        "captured_count": len(captures),
        "captures": captures,
        "recommendations": recommendations,
        "errors": errors,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    print(json.dumps(run_once(), ensure_ascii=False, indent=2, default=str))
