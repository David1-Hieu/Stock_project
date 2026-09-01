"""End-of-session data capture for watchlist stocks and market benchmarks."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from database import upsert_snapshot

try:
    from analysis.technical import compute_indicators, load_ohlcv  # type: ignore
except Exception:
    from technical import compute_indicators, load_ohlcv  # type: ignore

BENCHMARKS = ("VNINDEX", "VN30")


def _float(value: Any):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _capture_benchmark(symbol: str) -> Dict[str, Any]:
    """Benchmarks only need market/technical fields, not stock scoring."""
    raw = load_ohlcv(symbol=symbol, days=260)
    enriched = compute_indicators(raw)
    if enriched.empty:
        raise ValueError(f"Không có dữ liệu indicator cho {symbol}")
    latest = enriched.iloc[-1]
    snapshot = {
        "symbol": symbol,
        "trade_date": str(latest.get("date"))[:10],
        "open": _float(latest.get("open")),
        "high": _float(latest.get("high")),
        "low": _float(latest.get("low")),
        "close": _float(latest.get("close")),
        "volume": _float(latest.get("volume")),
        "rsi": _float(latest.get("rsi")),
        "macd": _float(latest.get("macd")),
        "macd_signal": _float(latest.get("macd_signal")),
        "ema20": _float(latest.get("ema20")),
        "ema50": _float(latest.get("ema50")),
        "ema200": _float(latest.get("ema200")),
        "technical_score": None,
        "fundamental_score": None,
        "valuation_score": None,
        "risk_score": None,
        "final_score": None,
        "is_benchmark": 1,
        "captured_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
    }
    return upsert_snapshot(snapshot)


def capture_symbol(symbol: str, is_benchmark: bool = False) -> Dict[str, Any]:
    """Capture one EOD snapshot.

    For stocks, compute scores on demand from the symbol's current technical and
    fundamental data. This deliberately does NOT depend on latest batch screening,
    because a Watchlist symbol may never have been part of that batch.
    """
    symbol = symbol.upper().strip()
    if is_benchmark:
        return _capture_benchmark(symbol)

    from services.analysis_service import analysis_bundle_to_snapshot, get_analysis_bundle

    bundle = get_analysis_bundle(symbol, chart_days=30)
    snapshot = analysis_bundle_to_snapshot(bundle)
    if not snapshot:
        detail = (bundle.get("errors") or {}).get("technical") or "không tạo được snapshot"
        raise ValueError(f"Không capture được {symbol}: {detail}")
    return upsert_snapshot(snapshot)
