"""Five-trading-session analysis using persisted EOD snapshots."""
from __future__ import annotations

import math
from statistics import pstdev
from typing import Any, Dict, List, Optional

from database import get_snapshots


def _num(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except Exception:
        return None


def _return_pct(first: Optional[float], last: Optional[float]) -> Optional[float]:
    if first in (None, 0) or last is None:
        return None
    return (last / first - 1.0) * 100.0


def _daily_returns(closes: List[float]) -> List[float]:
    result = []
    for a, b in zip(closes, closes[1:]):
        if a:
            result.append((b / a - 1.0) * 100.0)
    return result


def _max_drawdown_pct(closes: List[float]) -> Optional[float]:
    if not closes:
        return None
    peak = closes[0]
    worst = 0.0
    for value in closes:
        peak = max(peak, value)
        if peak:
            worst = min(worst, (value / peak - 1.0) * 100.0)
    return worst


def _benchmark_return(symbol: str, sessions: int) -> Optional[float]:
    rows = get_snapshots(symbol, sessions)
    if len(rows) < sessions:
        return None
    rows = rows[-sessions:]
    return _return_pct(_num(rows[0].get("close")), _num(rows[-1].get("close")))


def analyze_symbol(symbol: str, sessions: int = 5) -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    rows = get_snapshots(symbol, sessions)
    if len(rows) < sessions:
        return {
            "success": False,
            "symbol": symbol,
            "required_sessions": sessions,
            "available_sessions": len(rows),
            "error": f"Chưa đủ {sessions} phiên theo dõi.",
        }
    rows = rows[-sessions:]
    closes = [_num(x.get("close")) for x in rows]
    valid_closes = [x for x in closes if x is not None]
    if len(valid_closes) < sessions:
        return {"success": False, "symbol": symbol, "error": "Thiếu giá đóng cửa trong snapshot."}

    stock_return = _return_pct(valid_closes[0], valid_closes[-1])
    vnindex_return = _benchmark_return("VNINDEX", sessions)
    vn30_return = _benchmark_return("VN30", sessions)
    daily = _daily_returns(valid_closes)
    volatility = pstdev(daily) if len(daily) >= 2 else 0.0

    first, last = rows[0], rows[-1]
    technical_start = _num(first.get("technical_score"))
    technical_end = _num(last.get("technical_score"))
    rsi_start = _num(first.get("rsi"))
    rsi_end = _num(last.get("rsi"))

    result = {
        "success": True,
        "symbol": symbol,
        "window_sessions": sessions,
        "start_date": first.get("trade_date"),
        "end_date": last.get("trade_date"),
        "analysis_date": last.get("trade_date"),
        "start_close": round(valid_closes[0], 4),
        "end_close": round(valid_closes[-1], 4),
        # Trung bình số học của giá đóng cửa 5 phiên gần nhất.
        # Giữ return_5d riêng vì Recommendation Engine và Relative Strength vẫn cần tỷ suất sinh lời.
        "average_close_5d": round(sum(valid_closes) / len(valid_closes), 4),
        "return_5d": round(stock_return, 2) if stock_return is not None else None,
        "volatility_5d": round(volatility, 2),
        "max_drawdown_5d": round(_max_drawdown_pct(valid_closes) or 0.0, 2),
        "vnindex_return_5d": round(vnindex_return, 2) if vnindex_return is not None else None,
        "vn30_return_5d": round(vn30_return, 2) if vn30_return is not None else None,
        "relative_strength_vnindex": round(stock_return - vnindex_return, 2) if stock_return is not None and vnindex_return is not None else None,
        "relative_strength_vn30": round(stock_return - vn30_return, 2) if stock_return is not None and vn30_return is not None else None,
        "technical_score_start": technical_start,
        "technical_score_end": technical_end,
        "technical_score_change": round(technical_end - technical_start, 2) if technical_start is not None and technical_end is not None else None,
        "rsi_start": rsi_start,
        "rsi_end": rsi_end,
        "rsi_change": round(rsi_end - rsi_start, 2) if rsi_start is not None and rsi_end is not None else None,
        "macd_end": _num(last.get("macd")),
        "macd_signal_end": _num(last.get("macd_signal")),
        "ema20_end": _num(last.get("ema20")),
        "ema50_end": _num(last.get("ema50")),
        "ema200_end": _num(last.get("ema200")),
        "final_score": _num(last.get("final_score")),
        "sessions": rows,
    }
    return result
