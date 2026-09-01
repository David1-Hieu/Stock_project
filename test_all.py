"""Test toàn bộ project AI Stock Dashboard.

Cách chạy:
    python test_all.py all
    python test_all.py technical
    python test_all.py fundamental
    python test_all.py ollama
    python test_all.py flask
    python test_all.py batch
    python test_all.py full --symbol FPT
    python test_all.py report --symbol VCB --format html

Bản v3:
- batch mặc định test 3 mã FPT,VCB,VNM.
- flask chỉ smoke-test endpoint thật, tránh fail giả vì route string.
"""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")



def print_header(title: str) -> None:
    print("\n" + "=" * 88)
    print(title)
    print("=" * 88)


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def import_first(*module_names: str):
    last_error: Optional[Exception] = None

    for module_name in module_names:
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            last_error = exc

    raise ImportError(f"Không import được module nào trong: {module_names}") from last_error


def test_technical(symbol: str = "VNM") -> Dict[str, Any]:
    print_header(f"TEST TECHNICAL — {symbol}")

    technical = import_first("analysis.technical", "technical")
    start = time.perf_counter()

    summary = technical.get_technical_summary(symbol, days=180)
    elapsed = time.perf_counter() - start

    compact = {
        "symbol": summary.get("symbol"),
        "last_price": summary.get("last_price"),
        "last_date": summary.get("last_date"),
        "trend": summary.get("trend"),
        "rsi": (summary.get("indicators") or {}).get("rsi"),
        "macd": (summary.get("indicators") or {}).get("macd"),
        "active_signals": [
            key
            for key, value in (summary.get("signals") or {}).items()
            if isinstance(value, dict) and value.get("active")
        ],
        "elapsed_seconds": round(elapsed, 2),
    }

    print_json(compact)
    return {"success": True, "test": "technical", "result": compact}


def test_fundamental(symbol: str = "VCB") -> Dict[str, Any]:
    print_header(f"TEST FUNDAMENTAL — {symbol}")

    fundamental = import_first("analysis.fundamental", "fundamental")
    start = time.perf_counter()

    summary = fundamental.get_fundamental_summary(symbol)
    elapsed = time.perf_counter() - start

    score = summary.get("score") or {}
    latest_ratio = (summary.get("ratios") or [{}])[0] if summary.get("ratios") else {}

    compact = {
        "symbol": summary.get("symbol"),
        "score": score.get("score"),
        "grade": score.get("grade"),
        "pe": latest_ratio.get("pe"),
        "pb": latest_ratio.get("pb"),
        "roe": latest_ratio.get("roe"),
        "roa": latest_ratio.get("roa"),
        "debt_equity": latest_ratio.get("debt_equity"),
        "generated_at": summary.get("generated_at"),
        "elapsed_seconds": round(elapsed, 2),
    }

    print_json(compact)
    return {"success": True, "test": "fundamental", "result": compact}


def test_ollama() -> Dict[str, Any]:
    print_header("TEST OLLAMA")

    from agent.ollama_client import get_client

    start = time.perf_counter()
    client = get_client()
    models = client.list_models()
    elapsed = time.perf_counter() - start

    result = {
        "online": True,
        "models": models,
        "elapsed_seconds": round(elapsed, 2),
    }

    print_json(result)
    return {"success": True, "test": "ollama", "result": result}


def test_full_pipeline(symbol: str = "FPT") -> Dict[str, Any]:
    print_header(f"TEST FULL PIPELINE — {symbol}")

    from agent.agent import get_agent

    start = time.perf_counter()
    result = get_agent().full_report(symbol)
    elapsed = time.perf_counter() - start

    compact = {
        "symbol": result.get("symbol"),
        "score": result.get("score"),
        "grade": result.get("grade"),
        "llm_fallback_used": result.get("llm_fallback_used"),
        "has_comprehensive_analysis": bool(result.get("comprehensive_analysis")),
        "error": result.get("error"),
        "generated_at": result.get("generated_at"),
        "elapsed_seconds": round(elapsed, 2),
    }

    print_json(compact)
    return {"success": not bool(result.get("error")), "test": "full", "result": compact}


def test_report(symbol: str = "FPT", fmt: str = "html") -> Dict[str, Any]:
    print_header(f"TEST REPORT — {symbol} — {fmt}")

    from reporter.report_generator import generate_report

    start = time.perf_counter()
    result = generate_report(symbol, format=fmt)
    elapsed = time.perf_counter() - start

    compact = {
        "success": result.get("success"),
        "symbol": result.get("symbol"),
        "format": result.get("format"),
        "file_path": result.get("file_path"),
        "error": result.get("error"),
        "llm_fallback_used": result.get("llm_fallback_used"),
        "elapsed_seconds": round(elapsed, 2),
    }

    print_json(compact)
    return {"success": bool(result.get("success")), "test": "report", "result": compact}


def test_batch(symbols: str = "FPT,VCB,VNM", no_fundamental: bool = True) -> Dict[str, Any]:
    """Test batch bằng cách gọi trực tiếp collect_many().

    Bản trước chạy subprocess rồi dò symbol trong stdout nên dễ fail giả.
    Bản này kiểm tra dữ liệu trả về thật từ batch_collect.collect_many().
    """
    print_header(f"TEST BATCH — {symbols}")

    batch_collect = import_first("batch_collect")
    collect_many = getattr(batch_collect, "collect_many", None)
    parse_symbols = getattr(batch_collect, "parse_symbols", None)

    if collect_many is None:
        raise RuntimeError("Không tìm thấy hàm collect_many trong batch_collect.py")

    if parse_symbols is not None:
        requested_symbols = parse_symbols(symbols)
    else:
        requested_symbols = [s.strip().upper() for s in symbols.replace(";", ",").split(",") if s.strip()]

    output_dir = PROJECT_ROOT / "batch_results" / "test_run"

    start = time.perf_counter()
    result_raw = collect_many(
        symbols=requested_symbols,
        output_dir=output_dir,
        include_fundamental=not no_fundamental,
        delay_seconds=3,
        force_refresh=False,
        technical_days=180,
    )
    elapsed = time.perf_counter() - start

    top_rows = result_raw.get("top") or []
    count = result_raw.get("count")
    csv_path = result_raw.get("csv_path")
    json_path = result_raw.get("json_path")

    returned_symbols = []
    for row in top_rows:
        if isinstance(row, dict) and row.get("symbol"):
            returned_symbols.append(str(row["symbol"]).upper())

    missing_symbols = [sym for sym in requested_symbols if sym not in returned_symbols]

    result = {
        "success": bool(result_raw.get("success")) and count == len(requested_symbols) and not missing_symbols,
        "requested_symbols": requested_symbols,
        "returned_symbols": returned_symbols,
        "missing_symbols": missing_symbols,
        "count": count,
        "csv_path": csv_path,
        "json_path": json_path,
        "include_fundamental": not no_fundamental,
        "errors": result_raw.get("errors"),
        "elapsed_seconds": round(elapsed, 2),
    }

    print_json(result)
    return {"success": bool(result["success"]), "test": "batch", "result": result}


def test_flask_routes() -> Dict[str, Any]:
    """Smoke-test Flask.

    Không kiểm tra route string quá cứng nữa.
    Chỉ cần:
    - import được app.py
    - trang chủ trả 200
    - /api/screening/latest trả JSON
    - /api/agent/status trả 200 hoặc 503
    """
    print_header("TEST FLASK SMOKE")

    import app as app_module  # type: ignore

    flask_app = getattr(app_module, "app", None)
    if flask_app is None:
        raise RuntimeError("Không tìm thấy biến app trong app.py")

    routes = sorted(str(rule) for rule in flask_app.url_map.iter_rules())

    checks = []
    with flask_app.test_client() as client:
        home = client.get("/")
        checks.append({
            "endpoint": "/",
            "status_code": home.status_code,
            "pass": home.status_code == 200,
        })

        screening = client.get("/api/screening/latest")
        screening_json = None
        try:
            screening_json = screening.get_json()
        except Exception:
            pass
        checks.append({
            "endpoint": "/api/screening/latest",
            "status_code": screening.status_code,
            "json": isinstance(screening_json, dict),
            "count": screening_json.get("count") if isinstance(screening_json, dict) else None,
            "pass": screening.status_code == 200 and isinstance(screening_json, dict),
        })

        status = client.get("/api/agent/status")
        status_json = None
        try:
            status_json = status.get_json()
        except Exception:
            pass
        checks.append({
            "endpoint": "/api/agent/status",
            "status_code": status.status_code,
            "json": isinstance(status_json, dict),
            "pass": status.status_code in {200, 503} and isinstance(status_json, dict),
        })

    result = {
        "success": all(item["pass"] for item in checks),
        "checks": checks,
        "routes": routes,
    }

    print_json(result)
    return {"success": bool(result["success"]), "test": "flask", "result": result}


def run_test(name: str, args: argparse.Namespace) -> Dict[str, Any]:
    tests: Dict[str, Callable[[], Dict[str, Any]]] = {
        "technical": lambda: test_technical(args.symbol or "VNM"),
        "fundamental": lambda: test_fundamental(args.symbol or "VCB"),
        "ollama": test_ollama,
        "full": lambda: test_full_pipeline(args.symbol or "FPT"),
        "report": lambda: test_report(args.symbol or "FPT", args.format),
        "batch": lambda: test_batch(args.symbols, args.no_fundamental),
        "flask": test_flask_routes,
    }

    if name not in tests:
        raise ValueError(f"Test không hợp lệ: {name}")

    try:
        return tests[name]()
    except Exception as exc:
        print(f"❌ FAILED: {name}: {exc}")
        return {
            "success": False,
            "test": name,
            "error": str(exc),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Test toàn bộ AI Stock Dashboard")
    parser.add_argument(
        "test",
        nargs="?",
        default="all",
        choices=["technical", "fundamental", "ollama", "full", "report", "batch", "flask", "all"],
        help="Test cần chạy",
    )
    parser.add_argument("--symbol", default="", help="Mã cổ phiếu cho test đơn lẻ")
    parser.add_argument("--symbols", default="FPT,VCB,VNM", help="Danh sách mã cho batch test")
    parser.add_argument("--format", default="html", choices=["html", "pdf"], help="Format report")
    parser.add_argument(
        "--with-fundamental",
        dest="no_fundamental",
        action="store_false",
        help="Batch test có lấy cả fundamental, sẽ chậm hơn và dễ rate limit hơn",
    )
    parser.set_defaults(no_fundamental=True)

    args = parser.parse_args()

    if args.test == "all":
        # Không chạy full/report mặc định vì chúng gọi Ollama lâu.
        ordered = ["technical", "fundamental", "ollama", "flask", "batch"]
    else:
        ordered = [args.test]

    results = [run_test(name, args) for name in ordered]

    print_header("SUMMARY")
    ok = sum(1 for r in results if r.get("success"))
    total = len(results)

    for r in results:
        status = "PASS" if r.get("success") else "FAIL"
        print(f"{status:4} | {r.get('test')}")

    print(f"\nKết quả: {ok}/{total} PASS")

    if ok != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
