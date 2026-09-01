from __future__ import annotations

import re
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from agent.chatbot import ask as ask_chatbot
from database import (
    add_watchlist,
    get_holdings,
    get_latest_recommendation,
    get_latest_snapshot,
    get_snapshots,
    get_watchlist,
    list_recommendations,
    remove_holding,
    remove_watchlist,
    upsert_holding,
    upsert_snapshot,
)
from monitoring.data_helpers import latest_screening_rows
from monitoring.five_day_analyzer import analyze_symbol
from monitoring.run_eod import run_once
from recommendation.engine import recommend

features_bp = Blueprint("features", __name__)
SYMBOL_RE = re.compile(r"^[A-Z0-9._-]{1,12}$")


def _symbol(value: Any) -> str:
    symbol = str(value or "").upper().strip()
    if not SYMBOL_RE.match(symbol):
        raise ValueError("Mã cổ phiếu không hợp lệ")
    return symbol


@features_bp.get("/api/watchlist")
def api_watchlist_get():
    items = get_watchlist()
    enriched = []
    for item in items:
        symbol = item["symbol"]
        five_day = analyze_symbol(symbol, sessions=5)
        enriched.append({
            **item,
            "latest_snapshot": get_latest_snapshot(symbol),
            "latest_recommendation": get_latest_recommendation(symbol),
            # Tính trực tiếp từ 5 snapshot gần nhất để cột 5D không phụ thuộc
            # vào việc Recommendation Engine đã chạy hay chưa.
            "five_day_analysis": five_day,
        })
    return jsonify({"success": True, "data": enriched})


@features_bp.post("/api/watchlist")
def api_watchlist_add():
    body = request.get_json(silent=True) or {}
    try:
        symbol = _symbol(body.get("symbol"))
        item = add_watchlist(symbol, str(body.get("note") or ""))

        # When the request comes from the Analysis page, persist the already loaded
        # analysis snapshot so Watchlist can show Close / Final Score immediately.
        # Manual additions without a snapshot still work and will be populated by EOD.
        snapshot = body.get("snapshot")
        saved_snapshot = None
        if isinstance(snapshot, dict):
            snapshot = {**snapshot, "symbol": symbol, "is_benchmark": 0}
            if snapshot.get("trade_date"):
                saved_snapshot = upsert_snapshot(snapshot)

        return jsonify({"success": True, "data": item, "snapshot": saved_snapshot}), 201
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@features_bp.delete("/api/watchlist/<symbol>")
def api_watchlist_delete(symbol: str):
    try:
        removed = remove_watchlist(_symbol(symbol))
        return jsonify({"success": removed})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@features_bp.get("/api/portfolio")
def api_portfolio_get():
    data = []
    for row in get_holdings():
        snap = get_latest_snapshot(row["symbol"])
        current = (snap or {}).get("close")
        avg = row.get("avg_cost") or 0
        qty = row.get("quantity") or 0
        pnl_pct = ((current / avg - 1) * 100) if current is not None and avg else None
        data.append({**row, "current_price": current, "market_value": current * qty if current is not None else None, "pl_percent": pnl_pct})
    return jsonify({"success": True, "data": data})


@features_bp.post("/api/portfolio")
def api_portfolio_upsert():
    body = request.get_json(silent=True) or {}
    try:
        symbol = _symbol(body.get("symbol"))
        quantity = float(body.get("quantity", 0))
        avg_cost = float(body.get("avg_cost", 0))
        if quantity < 0 or avg_cost < 0:
            raise ValueError("quantity và avg_cost phải >= 0")
        row = upsert_holding(symbol, quantity, avg_cost, str(body.get("note") or ""))
        return jsonify({"success": True, "data": row}), 201
    except (ValueError, TypeError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@features_bp.delete("/api/portfolio/<symbol>")
def api_portfolio_delete(symbol: str):
    try:
        return jsonify({"success": remove_holding(_symbol(symbol))})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@features_bp.get("/api/monitor/<symbol>/history")
def api_monitor_history(symbol: str):
    try:
        return jsonify({"success": True, "data": get_snapshots(_symbol(symbol), int(request.args.get("limit", 20)))})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@features_bp.get("/api/monitor/<symbol>/5d")
def api_monitor_5d(symbol: str):
    try:
        analysis = analyze_symbol(_symbol(symbol), sessions=5)
        if analysis.get("success"):
            analysis = recommend(analysis)
        return jsonify(analysis), 200 if analysis.get("success") else 409
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@features_bp.post("/api/monitor/run")
def api_monitor_run():
    result = run_once()
    return jsonify(result), 200 if result.get("success") else 207


@features_bp.get("/api/recommendations/latest")
def api_recommendations():
    return jsonify({"success": True, "data": list_recommendations(limit=int(request.args.get("limit", 50)))})


@features_bp.get("/api/analysis-data/<symbol>")
def api_analysis_data(symbol: str):
    """Unified on-demand Analysis page payload.

    Loads technical OHLCV once, computes scores for the requested symbol directly,
    and therefore does not require the symbol to exist in the latest screening file.
    """
    try:
        code = _symbol(symbol)
        from services.analysis_service import get_analysis_bundle

        data = get_analysis_bundle(code, chart_days=int(request.args.get("chart_days", 90)))
        return jsonify(data), 200 if data.get("success") else 502
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": f"{type(exc).__name__}: {exc}"}), 500


@features_bp.get("/api/raw-analysis/<symbol>")
def api_raw_analysis(symbol: str):
    """Raw technical/fundamental analysis without invoking Ollama."""
    try:
        code = _symbol(symbol)
        analysis_type = str(request.args.get("type", "technical")).lower().strip()
        if analysis_type == "technical":
            try:
                from analysis.technical import get_technical_summary  # type: ignore
            except Exception:
                from technical import get_technical_summary  # type: ignore
            data = get_technical_summary(code)
        elif analysis_type == "fundamental":
            try:
                from analysis.fundamental import get_fundamental_summary  # type: ignore
            except Exception:
                from fundamental import get_fundamental_summary  # type: ignore
            data = get_fundamental_summary(code)
        else:
            return jsonify({"success": False, "error": "type chỉ nhận technical hoặc fundamental"}), 400
        return jsonify({"success": True, "symbol": code, "type": analysis_type, "data": data})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@features_bp.get("/api/chart/<symbol>")
def api_chart(symbol: str):
    try:
        code = _symbol(symbol)
        try:
            from analysis.technical import get_chart_data  # type: ignore
        except Exception:
            from technical import get_chart_data  # type: ignore
        return jsonify({"success": True, "symbol": code, "data": get_chart_data(code, days=int(request.args.get("days", 30)))})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@features_bp.post("/api/chat")
def api_chat():
    body = request.get_json(silent=True) or {}
    result = ask_chatbot(
        message=str(body.get("message") or ""),
        page=str(body.get("page") or ""),
        symbol=str(body.get("symbol") or ""),
    )
    return jsonify(result), 200 if result.get("success") else 503


@features_bp.get("/api/dashboard/summary")
def api_dashboard_summary():
    rows = latest_screening_rows()
    top = sorted(rows, key=lambda x: float(x.get("final_score") or x.get("screening_score") or 0), reverse=True)[:5]
    watchlist = get_watchlist()
    recs = list_recommendations(limit=5)
    return jsonify({
        "success": True,
        "top_stocks": top,
        "watchlist_count": len(watchlist),
        "portfolio_count": len(get_holdings()),
        "recent_recommendations": recs,
        "benchmarks": {
            "VNINDEX": get_latest_snapshot("VNINDEX"),
            "VN30": get_latest_snapshot("VN30"),
        },
    })
