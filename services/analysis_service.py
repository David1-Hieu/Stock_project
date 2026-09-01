from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value: Any, digits: int = 2) -> float | None:
    value = _safe_float(value)
    return round(value, digits) if value is not None else None


def _format_date(value: Any) -> str:
    try:
        return pd.to_datetime(value).strftime("%Y-%m-%d")
    except Exception:
        return str(value)


def _technical_module():
    try:
        from analysis import technical as technical_module  # type: ignore
    except Exception:
        import technical as technical_module  # type: ignore
    return technical_module


def _fundamental_summary(symbol: str) -> Dict[str, Any]:
    try:
        from analysis.fundamental import get_fundamental_summary  # type: ignore
    except Exception:
        from fundamental import get_fundamental_summary  # type: ignore
    return get_fundamental_summary(symbol)


def _score_stock(symbol: str, technical: Dict[str, Any] | None, fundamental: Dict[str, Any] | None) -> Dict[str, Any]:
    from screening.scoring_engine import score_stock

    return score_stock(symbol, technical, fundamental)


def build_technical_bundle(symbol: str, chart_days: int = 90) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Load OHLCV once and derive both technical summary and chart data.

    The previous Analysis page requested `/api/raw-analysis?...technical` and
    `/api/chart/...` in parallel. Those endpoints independently downloaded the same
    OHLCV history, while `get_technical_summary()` could make a second history call
    for EMA200. This service makes one sufficiently-long history request and reuses
    it for indicators, signals and the chart.
    """
    symbol = str(symbol).strip().upper()
    chart_days = max(30, min(int(chart_days), 240))
    technical = _technical_module()

    # Need >200 valid sessions for EMA200. Use a buffer so holidays/missing rows do
    # not leave the indicator frame empty.
    history_days = max(320, chart_days + 230)
    raw_df = technical.load_ohlcv(symbol=symbol, days=history_days)
    indicator_df = technical.compute_indicators(raw_df)
    signals = technical.detect_signals(indicator_df)
    latest = indicator_df.iloc[-1]

    ema50 = _safe_float(latest.get("ema50"))
    ema200 = _safe_float(latest.get("ema200"))
    if ema50 is not None and ema200 is not None:
        trend = "TĂNG" if ema50 > ema200 else "GIẢM" if ema50 < ema200 else "SIDEWAY"
    else:
        trend = "SIDEWAY"

    summary = {
        "symbol": symbol,
        "days": history_days,
        "last_price": _round_or_none(latest.get("close")),
        "last_date": _format_date(latest.get("date")),
        "indicators": {
            "rsi": _round_or_none(latest.get("rsi")),
            "macd": _round_or_none(latest.get("macd")),
            "macd_signal": _round_or_none(latest.get("macd_signal")),
            "macd_hist": _round_or_none(latest.get("macd_hist")),
            "bb_upper": _round_or_none(latest.get("bb_upper")),
            "bb_mid": _round_or_none(latest.get("bb_mid")),
            "bb_lower": _round_or_none(latest.get("bb_lower")),
            "ema20": _round_or_none(latest.get("ema20")),
            "ema50": _round_or_none(latest.get("ema50")),
            "ema200": _round_or_none(latest.get("ema200")),
            "volume_ma20": _round_or_none(latest.get("volume_ma20")),
        },
        "signals": signals,
        "trend": trend,
        "generated_at": datetime.now(VN_TZ).isoformat(timespec="seconds"),
    }

    chart_cols = ["date", "open", "high", "low", "close", "volume", "rsi", "macd", "ema20", "ema50"]
    chart_df = indicator_df[chart_cols].dropna().tail(chart_days).copy()
    chart_df["date"] = chart_df["date"].apply(_format_date)
    chart = chart_df.to_dict(orient="records")
    return summary, chart


def get_analysis_bundle(symbol: str, chart_days: int = 90) -> Dict[str, Any]:
    """Return on-demand analysis for any valid ticker.

    Scores are computed from the current symbol's fresh technical/fundamental data,
    not looked up from the latest batch screening file. This means a symbol does not
    have to be part of the last `batch_collect.py --symbols ...` run to get Final,
    Valuation, Technical and Risk scores on the Analysis page.
    """
    symbol = str(symbol).strip().upper()
    errors: Dict[str, str] = {}

    technical_data: Dict[str, Any] | None = None
    chart: List[Dict[str, Any]] = []
    try:
        technical_data, chart = build_technical_bundle(symbol, chart_days=chart_days)
    except Exception as exc:
        errors["technical"] = f"{type(exc).__name__}: {exc}"

    fundamental_data: Dict[str, Any] | None = None
    try:
        fundamental_data = _fundamental_summary(symbol)
    except Exception as exc:
        errors["fundamental"] = f"{type(exc).__name__}: {exc}"

    scoring: Dict[str, Any] | None = None
    try:
        scoring = _score_stock(symbol, technical_data, fundamental_data)
    except Exception as exc:
        errors["scoring"] = f"{type(exc).__name__}: {exc}"

    monitor: Dict[str, Any] | None = None
    try:
        from monitoring.five_day_analyzer import analyze_symbol
        from recommendation.engine import recommend

        monitor = analyze_symbol(symbol, sessions=5)
        if monitor.get("success"):
            monitor = recommend(monitor)
    except Exception as exc:
        errors["monitor"] = f"{type(exc).__name__}: {exc}"

    return {
        "success": technical_data is not None or fundamental_data is not None,
        "symbol": symbol,
        "technical": technical_data,
        "fundamental": fundamental_data,
        "scoring": scoring,
        "chart": chart,
        "monitor": monitor,
        "errors": errors,
    }


def analysis_bundle_to_snapshot(bundle: Dict[str, Any]) -> Dict[str, Any] | None:
    """Convert an on-demand Analysis bundle into a persistable daily snapshot.

    This lets a symbol added to Watchlist immediately show its latest close and
    component scores without waiting for the scheduled EOD monitor.
    """
    if not isinstance(bundle, dict):
        return None
    symbol = str(bundle.get("symbol") or "").upper().strip()
    technical = bundle.get("technical") or {}
    scoring = bundle.get("scoring") or {}
    chart = bundle.get("chart") or []
    if not symbol or not technical:
        return None

    latest_bar = chart[-1] if isinstance(chart, list) and chart else {}
    indicators = technical.get("indicators") or {}
    components = scoring.get("components") or {}

    def component_score(name: str):
        value = components.get(name) or {}
        return _safe_float(value.get("score") if isinstance(value, dict) else None)

    trade_date = str(technical.get("last_date") or latest_bar.get("date") or "")[:10]
    if not trade_date:
        return None

    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "open": _safe_float(latest_bar.get("open")),
        "high": _safe_float(latest_bar.get("high")),
        "low": _safe_float(latest_bar.get("low")),
        "close": _safe_float(technical.get("last_price") if technical.get("last_price") is not None else latest_bar.get("close")),
        "volume": _safe_float(latest_bar.get("volume")),
        "rsi": _safe_float(indicators.get("rsi")),
        "macd": _safe_float(indicators.get("macd")),
        "macd_signal": _safe_float(indicators.get("macd_signal")),
        "ema20": _safe_float(indicators.get("ema20")),
        "ema50": _safe_float(indicators.get("ema50")),
        "ema200": _safe_float(indicators.get("ema200")),
        "technical_score": component_score("technical"),
        "fundamental_score": component_score("fundamental"),
        "valuation_score": component_score("valuation"),
        "risk_score": component_score("risk"),
        "final_score": _safe_float(scoring.get("final_score")),
        "is_benchmark": 0,
        "captured_at": datetime.now(VN_TZ).isoformat(timespec="seconds"),
    }
