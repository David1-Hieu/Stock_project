"""Flask routes tích hợp AI Agent vào dashboard.

Cách dùng trong app.py:
    from ai_routes import register_ai_routes
    register_ai_routes(app)

Module này cố tình tách riêng để không phải sửa sâu app.py hiện có.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Blueprint, current_app, jsonify, request, send_from_directory, session
from werkzeug.utils import secure_filename

# Đảm bảo chạy được cả khi app.py/import module từ thư mục gốc project.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("ai_routes")

ai_bp = Blueprint("ai_routes", __name__)

CACHE_TTL_SECONDS = 10 * 60
_API_CACHE: Dict[str, Dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get_session_namespace() -> str:
    """Tạo namespace nhỏ trong Flask session để cache theo từng browser session."""
    namespace = session.get("_ai_cache_namespace")
    if not namespace:
        namespace = uuid.uuid4().hex
        session["_ai_cache_namespace"] = namespace
    return namespace


def _cache_get(key: str) -> Optional[Any]:
    item = _API_CACHE.get(key)
    if not item:
        return None

    age = time.time() - float(item.get("created_at", 0))
    if age > CACHE_TTL_SECONDS:
        _API_CACHE.pop(key, None)
        return None

    return item.get("data")


def _cache_set(key: str, data: Any) -> None:
    _API_CACHE[key] = {
        "created_at": time.time(),
        "data": data,
    }

    # Flask session cookie chỉ lưu key/timestamp nhỏ, không lưu data lớn.
    session_cache = session.get("_ai_cache_keys", {})
    session_cache[key] = int(time.time())
    session["_ai_cache_keys"] = session_cache


def _json_safe(value: Any) -> Any:
    """Chuyển numpy/pandas/object lạ thành JSON-safe để jsonify không lỗi."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]

    # numpy scalar / pandas Timestamp / decimal...
    try:
        if hasattr(value, "item"):
            return value.item()
    except Exception:
        pass

    try:
        if hasattr(value, "isoformat"):
            return value.isoformat()
    except Exception:
        pass

    return str(value)


def _is_ollama_error(data: Any) -> bool:
    if not isinstance(data, dict):
        return False

    message = str(data.get("error", "")).lower()
    return any(
        phrase in message
        for phrase in [
            "ollama",
            "localhost:11434",
            "connection refused",
            "không thể nhận phản hồi",
            "chưa được khởi động",
        ]
    )


def _get_report_dir() -> Path:
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    return reports_dir


def _make_file_url(file_path: str | os.PathLike[str]) -> str:
    filename = Path(file_path).name
    return f"/reports/{filename}"


def _find_latest_screening_file() -> Optional[Path]:
    batch_dir = PROJECT_ROOT / "batch_results"
    if not batch_dir.exists():
        return None

    files = sorted(
        batch_dir.glob("stock_screening_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def _extract_screening_rows(payload: Any) -> List[Dict[str, Any]]:
    """Tự dò danh sách cổ phiếu trong file screening JSON.

    batch_collect.py có thể lưu JSON theo nhiều dạng:
    - list trực tiếp: [{symbol, screening_score, ...}]
    - dict có key top/data/results/rows/stocks/items
    - dict lồng sâu hơn chứa một list các dict có trường symbol
    """
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]

    if not isinstance(payload, dict):
        return []

    # Các key phổ biến.
    candidate_keys = [
        "top",
        "data",
        "results",
        "rows",
        "stocks",
        "items",
        "screening",
        "records",
    ]

    for key in candidate_keys:
        value = payload.get(key)
        if isinstance(value, list):
            rows = [row for row in value if isinstance(row, dict)]
            if rows:
                return rows

    # Một số file có dạng {"success": true, "count": 3, "payload": {"top": [...]}}
    for value in payload.values():
        if isinstance(value, dict):
            rows = _extract_screening_rows(value)
            if rows:
                return rows

    # Fallback mạnh hơn: tìm list nào có dict chứa symbol/ticker/code.
    def looks_like_stock_rows(value: Any) -> bool:
        if not isinstance(value, list) or not value:
            return False
        dict_rows = [row for row in value if isinstance(row, dict)]
        if not dict_rows:
            return False
        sample = dict_rows[:5]
        return any(
            any(k in row for k in ["symbol", "ticker", "code", "screening_score", "last_price"])
            for row in sample
        )

    for value in payload.values():
        if looks_like_stock_rows(value):
            return [row for row in value if isinstance(row, dict)]

    return []


def _load_latest_screening() -> Dict[str, Any]:
    latest = _find_latest_screening_file()
    if not latest:
        return {
            "success": False,
            "error": "Chưa có file screening. Hãy chạy: python batch_collect.py --symbols FPT,VCB,VNM --delay 6",
            "data": [],
            "generated_at": _now_iso(),
        }

    try:
        with latest.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        rows = _extract_screening_rows(payload)

        # Nếu file có count nhưng parser không lấy được rows, trả thêm debug_keys để dễ sửa tiếp.
        debug_keys = list(payload.keys()) if isinstance(payload, dict) else []

        return {
            "success": True,
            "file_path": str(latest),
            "file_name": latest.name,
            "count": len(rows),
            "data": rows,
            "debug_keys": debug_keys,
            "generated_at": _now_iso(),
        }
    except Exception as exc:
        logger.exception("Không đọc được screening file %s", latest)
        return {
            "success": False,
            "error": f"Không đọc được screening file: {exc}",
            "data": [],
            "generated_at": _now_iso(),
        }


def _load_holdings_from_request_body() -> Optional[List[Dict[str, Any]]]:
    body = request.get_json(silent=True) or {}
    holdings = body.get("holdings")
    if isinstance(holdings, list):
        return holdings
    return None


def _load_holdings_from_database_module() -> Optional[List[Dict[str, Any]]]:
    """Thử gọi các hàm thường gặp trong database.py hiện có."""
    try:
        import database  # type: ignore
    except Exception:
        return None

    candidate_names = [
        "get_holdings",
        "get_all_holdings",
        "get_portfolio",
        "get_portfolio_holdings",
        "load_holdings",
    ]

    for name in candidate_names:
        func = getattr(database, name, None)
        if not callable(func):
            continue

        try:
            data = func()
            if isinstance(data, list):
                return [_normalize_holding(row) for row in data]
        except TypeError:
            # Một số hàm có thể cần db path/user id; bỏ qua để không crash.
            continue
        except Exception:
            logger.exception("Lỗi khi gọi database.%s()", name)
            continue

    return None


def _normalize_holding(row: Any) -> Dict[str, Any]:
    """Chuẩn hoá row từ dict/sqlite.Row/tuple thành format agent cần."""
    if isinstance(row, dict):
        d = dict(row)
    elif hasattr(row, "keys"):
        d = {k: row[k] for k in row.keys()}
    elif isinstance(row, (list, tuple)):
        # Fallback tuple phổ biến: symbol, quantity, avg_cost, current_price
        d = {}
        keys = ["symbol", "quantity", "avg_cost", "current_price", "pl_percent"]
        for i, value in enumerate(row[: len(keys)]):
            d[keys[i]] = value
    else:
        d = {"symbol": str(row)}

    symbol = str(d.get("symbol") or d.get("ticker") or d.get("code") or "").upper().strip()

    quantity = d.get("quantity", d.get("qty", d.get("shares", 0)))
    avg_cost = d.get("avg_cost", d.get("average_price", d.get("cost_basis", d.get("buy_price", 0))))
    current_price = d.get("current_price", d.get("price", d.get("last_price", 0)))
    pl_percent = d.get("pl_percent", d.get("pnl_percent", d.get("profit_loss_percent", 0)))

    return {
        "symbol": symbol,
        "quantity": quantity,
        "avg_cost": avg_cost,
        "current_price": current_price,
        "pl_percent": pl_percent,
    }


def _load_holdings_from_sqlite() -> Optional[List[Dict[str, Any]]]:
    """Fallback đọc SQLite nếu không biết database.py có hàm gì.

    Tự dò các bảng phổ biến: holdings, portfolio, positions.
    """
    candidate_paths = [
        PROJECT_ROOT / "data" / "portfolio.db",
        PROJECT_ROOT / "portfolio.db",
        PROJECT_ROOT / "data" / "stocks.db",
    ]

    db_path = next((p for p in candidate_paths if p.exists()), None)
    if not db_path:
        return None

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        table_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        tables = [r["name"] for r in table_rows]

        preferred = ["holdings", "portfolio", "positions", "stocks"]
        table = next((t for t in preferred if t in tables), tables[0] if tables else None)
        if not table:
            return None

        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        return [_normalize_holding(row) for row in rows]
    except Exception:
        logger.exception("Không đọc được holdings từ SQLite")
        return None
    finally:
        try:
            conn.close()  # type: ignore[name-defined]
        except Exception:
            pass


def _load_current_holdings() -> List[Dict[str, Any]]:
    """Lấy holdings hiện tại theo thứ tự ưu tiên: body -> database.py -> SQLite."""
    holdings = _load_holdings_from_request_body()
    if holdings is not None:
        return [_normalize_holding(h) for h in holdings]

    holdings = _load_holdings_from_database_module()
    if holdings is not None:
        return [h for h in holdings if h.get("symbol")]

    holdings = _load_holdings_from_sqlite()
    if holdings is not None:
        return [h for h in holdings if h.get("symbol")]

    return []


@ai_bp.get("/api/agent/status")
def api_agent_status():
    """Kiểm tra Ollama đang online không và liệt kê model."""
    base_url = current_app.config.get("OLLAMA_BASE_URL", "http://localhost:11434")
    recommended = "llama3.2"

    try:
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        response.raise_for_status()
        payload = response.json()

        raw_models = payload.get("models", [])
        models = []
        for item in raw_models:
            if isinstance(item, dict):
                name = item.get("name") or item.get("model")
                if name:
                    models.append(name)
            elif isinstance(item, str):
                models.append(item)

        if any("llama3.2:3b" in m for m in models):
            recommended = "llama3.2:3b"
        elif any("llama3.2" in m for m in models):
            recommended = "llama3.2"
        elif models:
            recommended = models[0]

        return jsonify(
            {
                "online": True,
                "models": models,
                "recommended_model": recommended,
                "base_url": base_url,
                "generated_at": _now_iso(),
            }
        )
    except Exception as exc:
        return (
            jsonify(
                {
                    "online": False,
                    "models": [],
                    "recommended_model": recommended,
                    "base_url": base_url,
                    "error": str(exc),
                    "hint": "Khởi động Ollama bằng lệnh: ollama serve",
                    "generated_at": _now_iso(),
                }
            ),
            503,
        )


@ai_bp.get("/api/analysis/<symbol>")
def api_analysis(symbol: str):
    """Phân tích technical/fundamental/full theo mã cổ phiếu."""
    symbol = secure_filename(symbol.upper().strip())
    analysis_type = request.args.get("type", "full").lower().strip()

    if analysis_type not in {"technical", "fundamental", "full"}:
        return (
            jsonify(
                {
                    "error": "type không hợp lệ. Chỉ dùng: technical, fundamental, full",
                    "symbol": symbol,
                    "generated_at": _now_iso(),
                }
            ),
            400,
        )

    force = request.args.get("force", "0").lower() in {"1", "true", "yes"}
    cache_key = f"{_get_session_namespace()}:analysis:{analysis_type}:{symbol}"

    if not force:
        cached = _cache_get(cache_key)
        if cached is not None:
            payload = dict(cached)
            payload["cache_hit"] = True
            return jsonify(_json_safe(payload))

    try:
        from agent.agent import get_agent

        agent = get_agent()

        if analysis_type == "technical":
            result = agent.analyze_technical(symbol)
        elif analysis_type == "fundamental":
            result = agent.analyze_fundamental(symbol)
        else:
            result = agent.full_report(symbol)

        result = _json_safe(result)
        if isinstance(result, dict):
            result["cache_hit"] = False
            result["analysis_type"] = analysis_type

        if _is_ollama_error(result):
            return jsonify(result), 503

        _cache_set(cache_key, result)
        return jsonify(result)
    except Exception as exc:
        logger.exception("Lỗi /api/analysis/%s?type=%s", symbol, analysis_type)
        status = 503 if "ollama" in str(exc).lower() else 500
        return (
            jsonify(
                {
                    "error": str(exc),
                    "symbol": symbol,
                    "analysis_type": analysis_type,
                    "hint": "Nếu lỗi liên quan Ollama, hãy chạy: ollama serve",
                    "generated_at": _now_iso(),
                }
            ),
            status,
        )


@ai_bp.get("/api/report/<symbol>")
def api_report(symbol: str):
    """Tạo báo cáo HTML/PDF và trả URL để dashboard mở/tải."""
    symbol = secure_filename(symbol.upper().strip())
    fmt = request.args.get("format", "html").lower().strip()

    if fmt not in {"html", "pdf"}:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "format không hợp lệ. Chỉ dùng: html hoặc pdf",
                    "symbol": symbol,
                    "generated_at": _now_iso(),
                }
            ),
            400,
        )

    force = request.args.get("force", "0").lower() in {"1", "true", "yes"}
    cache_key = f"{_get_session_namespace()}:report:{fmt}:{symbol}"

    if not force:
        cached = _cache_get(cache_key)
        if cached is not None and Path(str(cached.get("file_path", ""))).exists():
            payload = dict(cached)
            payload["cache_hit"] = True
            return jsonify(_json_safe(payload))

    try:
        from reporter.report_generator import generate_report

        result = generate_report(symbol, format=fmt)
        result = _json_safe(result)

        if isinstance(result, dict) and result.get("file_path"):
            result["file_url"] = _make_file_url(str(result["file_path"]))
            result["cache_hit"] = False

        if not result.get("success"):
            return jsonify(result), 500

        _cache_set(cache_key, result)
        return jsonify(result)
    except Exception as exc:
        logger.exception("Lỗi /api/report/%s?format=%s", symbol, fmt)
        return (
            jsonify(
                {
                    "success": False,
                    "error": str(exc),
                    "symbol": symbol,
                    "format": fmt,
                    "generated_at": _now_iso(),
                }
            ),
            500,
        )


@ai_bp.get("/reports/<path:filename>")
def serve_report_file(filename: str):
    """Serve báo cáo đã tạo, chỉ cho phép .html và .pdf."""
    safe_name = secure_filename(Path(filename).name)
    suffix = Path(safe_name).suffix.lower()

    if suffix not in {".html", ".pdf"}:
        return jsonify({"error": "Chỉ cho phép tải file .html hoặc .pdf"}), 403

    reports_dir = _get_report_dir()
    target = reports_dir / safe_name

    if not target.exists():
        return jsonify({"error": f"Không tìm thấy báo cáo: {safe_name}"}), 404

    return send_from_directory(reports_dir, safe_name, as_attachment=False)


@ai_bp.post("/api/portfolio/overview")
def api_portfolio_overview():
    """Tạo nhận định AI cho danh mục hiện tại."""
    force = request.args.get("force", "0").lower() in {"1", "true", "yes"}
    cache_key = f"{_get_session_namespace()}:portfolio_overview"

    if not force:
        cached = _cache_get(cache_key)
        if cached is not None:
            payload = dict(cached)
            payload["cache_hit"] = True
            return jsonify(_json_safe(payload))

    holdings = _load_current_holdings()
    if not holdings:
        return (
            jsonify(
                {
                    "error": "Không tìm thấy holdings. Hãy kiểm tra database.py hoặc gửi body JSON {'holdings': [...]} để test.",
                    "holdings": [],
                    "generated_at": _now_iso(),
                }
            ),
            400,
        )

    try:
        from agent.agent import get_agent

        result = get_agent().portfolio_overview(holdings)
        result = _json_safe(result)

        if isinstance(result, dict):
            result["cache_hit"] = False

        if _is_ollama_error(result):
            return jsonify(result), 503

        _cache_set(cache_key, result)
        return jsonify(result)
    except Exception as exc:
        logger.exception("Lỗi /api/portfolio/overview")
        status = 503 if "ollama" in str(exc).lower() else 500
        return (
            jsonify(
                {
                    "error": str(exc),
                    "hint": "Nếu lỗi liên quan Ollama, hãy chạy: ollama serve",
                    "holdings": holdings,
                    "generated_at": _now_iso(),
                }
            ),
            status,
        )


@ai_bp.get("/api/screening/latest")
def api_screening_latest():
    """Đọc file batch_results/stock_screening_*.json mới nhất để dashboard hiển thị ranking."""
    result = _load_latest_screening()
    status = 200 if result.get("success") else 404
    return jsonify(_json_safe(result)), status


def register_ai_routes(app):
    """Đăng ký blueprint AI vào Flask app."""
    if "ai_routes" not in app.blueprints:
        app.register_blueprint(ai_bp)
        logger.info("Đã đăng ký AI routes")
    return app


if __name__ == "__main__":
    # Test nhanh status mà không cần app.py.
    from flask import Flask

    app = Flask(__name__)
    app.secret_key = "dev-only"
    register_ai_routes(app)
    app.run(debug=True, port=5001)
