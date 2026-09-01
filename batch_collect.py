"""Batch collector/screener v2 for Stock_analyze.

Upgrade over the original project:
- keeps the existing technical/fundamental data collectors;
- separates Fundamental, Valuation, Technical and Risk scores;
- adds hard filters, explainability, final ranking and backward-compatible fields;
- preserves cache/rate-limit friendly CLI usage.

Examples:
    python batch_collect.py --symbols FPT,VCB,VNM --delay 6
    python batch_collect.py --universe VN30 --limit 5 --delay 6
    python batch_collect.py --universe VN30 --delay 6
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from services.reference_service import get_index_members

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from analysis.technical import get_technical_summary  # type: ignore
except Exception:
    from technical import get_technical_summary  # type: ignore

try:
    from analysis.fundamental import get_fundamental_summary  # type: ignore
except Exception:
    from fundamental import get_fundamental_summary  # type: ignore

from screening.scoring_engine import grade_from_score as v2_grade_from_score
from screening.scoring_engine import score_stock

LOGGER = logging.getLogger("batch_collect")

UNIVERSES: Dict[str, List[str]] = {
    "MY_PORTFOLIO": ["HPG", "ACB", "MBB", "DIG", "PDR"],
    "VN30": [
        "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
        "MBB", "MSN", "MWG", "PLX", "SAB", "SHB", "SSI", "STB", "TCB", "TPB",
        "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
    ],
    "BANKS": ["VCB", "BID", "CTG", "TCB", "MBB", "ACB", "STB", "VPB", "HDB", "VIB", "TPB", "SHB"],
    "TECH": ["FPT", "CMG", "ELC"],
    "STEEL": ["HPG", "HSG", "NKG", "TLH", "SMC"],
    "RETAIL": ["MWG", "FRT", "DGW", "PNJ", "MSN"],
    "REAL_ESTATE": ["VHM", "VIC", "VRE", "NVL", "KDH", "DXG", "PDR", "NLG"],
    "SECURITIES": ["SSI", "VND", "VCI", "HCM", "MBS", "SHS", "FTS"],
    "ENERGY": ["GAS", "PLX", "PVD", "PVS", "BSR", "POW"],
}

CSV_COLUMNS = [
    "rank", "eligible_rank", "symbol",
    "screening_score", "final_score", "fundamental_score", "valuation_score", "technical_score", "risk_score",
    "grade", "eligible", "action", "filter_reasons", "score_explanation",
    "last_price", "last_date", "trend", "rsi", "macd", "macd_signal", "macd_hist",
    "ema20", "ema50", "ema200", "bb_upper", "bb_lower", "active_signals",
    "pe", "pb", "roe", "roa", "debt_equity", "eps", "net_margin",
    "revenue_growth_yoy", "profit_growth_yoy", "latest_revenue", "latest_net_income",
    "legacy_fundamental_score", "error", "generated_at",
]

RATE_LIMIT_HINTS = ["ratelimit", "rate limit", "rate_limit", "too many requests", "giới hạn api", "gioi han api", "429"]


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper()


def parse_symbols(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    result: List[str] = []
    seen = set()
    for part in raw.replace(";", ",").split(","):
        symbol = normalize_symbol(part)
        if symbol and symbol not in seen:
            result.append(symbol)
            seen.add(symbol)
    return result


def get_universe(name: str) -> List[str]:
    key = str(name).strip().upper()
    if key not in UNIVERSES:
        raise ValueError(f"Không có universe '{name}'. Các lựa chọn: {', '.join(sorted(UNIVERSES))}")
    if key == "VN30":
        # Dynamic first; giữ list hiện tại làm fallback nếu provider/reference lỗi.
        return get_index_members("VN30", fallback=list(UNIVERSES[key]))
    return list(UNIVERSES[key])


def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip().replace(",", "").replace("%", "")
            if value.lower() in {"", "none", "null", "nan", "n/a", "không có dữ liệu"}:
                return None
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    except Exception:
        return None


def round_float(value: Any, ndigits: int = 2) -> Optional[float]:
    number = safe_float(value)
    return round(number, ndigits) if number is not None else None


def get_nested(data: Dict[str, Any], path: Sequence[str], default: Any = None) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def cache_file_path(cache_dir: Path, symbol: str, data_type: str) -> Path:
    return cache_dir / f"{normalize_symbol(symbol)}_{data_type}.json"


def is_cache_fresh(path: Path, ttl_hours: float) -> bool:
    if ttl_hours <= 0 or not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) <= ttl_hours * 3600


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        LOGGER.debug("Không đọc được cache %s: %s", path, exc)
        return None


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_cached_or_fetch(symbol: str, data_type: str, cache_dir: Path, ttl_hours: float, force_refresh: bool, fetch_func) -> Dict[str, Any]:
    path = cache_file_path(cache_dir, symbol, data_type)
    if not force_refresh and is_cache_fresh(path, ttl_hours):
        cached = load_json(path)
        if cached is not None:
            cached["_cache_used"] = True
            LOGGER.info("Dùng cache %s cho %s", data_type, symbol)
            return cached
    data = fetch_func()
    if not isinstance(data, dict):
        raise ValueError(f"fetch_func cho {symbol}/{data_type} không trả dict")
    data["_cache_used"] = False
    save_json(path, data)
    return data


def active_signal_names(signals: Dict[str, Any]) -> List[str]:
    return [key for key, info in signals.items() if isinstance(info, dict) and bool(info.get("active"))]


def latest_ratio(fundamental: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    ratios = get_nested(fundamental or {}, ["ratios"], [])
    return ratios[0] if isinstance(ratios, list) and ratios and isinstance(ratios[0], dict) else {}


def latest_income(fundamental: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    income = get_nested(fundamental or {}, ["income"], [])
    return income[0] if isinstance(income, list) and income and isinstance(income[0], dict) else {}


def grade_from_score(score: Optional[float]) -> str:
    return v2_grade_from_score(score)


def compute_screening_score(technical: Optional[Dict[str, Any]], fundamental: Optional[Dict[str, Any]], symbol: str = "UNKNOWN") -> float:
    """Backward-compatible helper; now returns the v2 final score."""
    return float(score_stock(symbol, technical, fundamental).get("final_score", 0.0))


def _component_score(scoring: Dict[str, Any], name: str) -> Optional[float]:
    return round_float(get_nested(scoring, ["components", name, "score"]))


def make_stock_row(symbol: str, technical: Optional[Dict[str, Any]], fundamental: Optional[Dict[str, Any]], error: Optional[str] = None) -> Dict[str, Any]:
    indicators = get_nested(technical or {}, ["indicators"], {}) or {}
    signals = get_nested(technical or {}, ["signals"], {}) or {}
    ratio = latest_ratio(fundamental)
    income = latest_income(fundamental)
    scoring = score_stock(symbol, technical, fundamental)

    positive = get_nested(scoring, ["explanation", "positive"], []) or []
    negative = get_nested(scoring, ["explanation", "negative"], []) or []
    explanation = " | ".join([*(str(x) for x in positive[:3]), *(f"⚠ {x}" for x in negative[:2])])
    filter_reasons = "; ".join(str(x) for x in get_nested(scoring, ["filters", "reasons"], []) or [])

    legacy_fundamental = round_float(get_nested(fundamental or {}, ["score", "score"]))
    row: Dict[str, Any] = {
        "rank": None,
        "eligible_rank": None,
        "symbol": normalize_symbol(symbol),
        # backward compatibility: screening_score remains the primary ranking score
        "screening_score": round_float(scoring.get("final_score")),
        "final_score": round_float(scoring.get("final_score")),
        "fundamental_score": _component_score(scoring, "fundamental"),
        "valuation_score": _component_score(scoring, "valuation"),
        "technical_score": _component_score(scoring, "technical"),
        "risk_score": _component_score(scoring, "risk"),
        "grade": scoring.get("grade"),
        "eligible": bool(scoring.get("eligible")),
        "action": scoring.get("action"),
        "filter_reasons": filter_reasons,
        "score_explanation": explanation,
        "last_price": round_float(get_nested(technical or {}, ["last_price"])),
        "last_date": get_nested(technical or {}, ["last_date"]),
        "trend": get_nested(technical or {}, ["trend"]),
        "rsi": round_float(indicators.get("rsi")),
        "macd": round_float(indicators.get("macd")),
        "macd_signal": round_float(indicators.get("macd_signal")),
        "macd_hist": round_float(indicators.get("macd_hist")),
        "ema20": round_float(indicators.get("ema20")),
        "ema50": round_float(indicators.get("ema50")),
        "ema200": round_float(indicators.get("ema200")),
        "bb_upper": round_float(indicators.get("bb_upper")),
        "bb_lower": round_float(indicators.get("bb_lower")),
        "active_signals": ",".join(active_signal_names(signals if isinstance(signals, dict) else {})),
        "pe": round_float(ratio.get("pe")),
        "pb": round_float(ratio.get("pb")),
        "roe": round_float(ratio.get("roe")),
        "roa": round_float(ratio.get("roa")),
        "debt_equity": round_float(ratio.get("debt_equity")),
        "eps": round_float(ratio.get("eps")),
        "net_margin": round_float(ratio.get("net_margin")),
        "revenue_growth_yoy": round_float(income.get("revenue_growth_yoy")),
        "profit_growth_yoy": round_float(income.get("profit_growth_yoy")),
        "latest_revenue": income.get("revenue_formatted") or round_float(income.get("revenue")),
        "latest_net_income": income.get("net_income_formatted") or round_float(income.get("net_income")),
        "legacy_fundamental_score": legacy_fundamental,
        "error": error,
        "generated_at": now_iso(),
        # nested diagnostic object retained in JSON; ignored by CSV writer
        "scoring_v2": scoring,
    }
    return row


def looks_like_rate_limit(error: Exception) -> bool:
    message = str(error).lower()
    return any(hint in message for hint in RATE_LIMIT_HINTS)


def collect_one_symbol(
    symbol: str,
    cache_dir: Path,
    cache_hours_technical: float = 6,
    cache_hours_fundamental: float = 24 * 7,
    include_fundamental: bool = True,
    force_refresh: bool = False,
    technical_days: int = 260,
) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)
    technical: Optional[Dict[str, Any]] = None
    fundamental: Optional[Dict[str, Any]] = None
    errors: List[str] = []

    try:
        technical = get_cached_or_fetch(
            normalized, "technical", cache_dir, cache_hours_technical, force_refresh,
            lambda: get_technical_summary(normalized, days=technical_days),
        )
    except Exception as exc:
        LOGGER.exception("Lỗi technical %s", normalized)
        errors.append(f"technical: {exc}")
        if looks_like_rate_limit(exc):
            raise

    if include_fundamental:
        try:
            fundamental = get_cached_or_fetch(
                normalized, "fundamental", cache_dir, cache_hours_fundamental, force_refresh,
                lambda: get_fundamental_summary(normalized),
            )
        except Exception as exc:
            LOGGER.exception("Lỗi fundamental %s", normalized)
            errors.append(f"fundamental: {exc}")
            if looks_like_rate_limit(exc):
                raise

    return make_stock_row(normalized, technical, fundamental, error=" | ".join(errors) if errors else None)


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore", delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def _ranking_key(item: Dict[str, Any]):
    # Eligible names always appear before names that fail hard filters.
    return (1 if item.get("eligible") else 0, safe_float(item.get("final_score")) or 0.0)


def collect_many(
    symbols: Sequence[str],
    output_dir: Path = Path("batch_results"),
    include_fundamental: bool = True,
    delay_seconds: float = 6,
    force_refresh: bool = False,
    technical_days: int = 260,
    cache_hours_technical: float = 6,
    cache_hours_fundamental: float = 24 * 7,
    stop_on_rate_limit: bool = False,
    rate_limit_sleep: float = 65,
) -> Dict[str, Any]:
    output_dir = Path(output_dir)
    cache_dir = output_dir / "cache"
    rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    unique_symbols: List[str] = []
    seen = set()
    for symbol in symbols:
        normalized = normalize_symbol(symbol)
        if normalized and normalized not in seen:
            unique_symbols.append(normalized)
            seen.add(normalized)

    started_at = now_iso()
    LOGGER.info("Bắt đầu collect %d mã: %s", len(unique_symbols), ", ".join(unique_symbols))

    for index, symbol in enumerate(unique_symbols, start=1):
        LOGGER.info("[%d/%d] Đang xử lý %s", index, len(unique_symbols), symbol)
        try:
            row = collect_one_symbol(
                symbol=symbol,
                cache_dir=cache_dir,
                cache_hours_technical=cache_hours_technical,
                cache_hours_fundamental=cache_hours_fundamental,
                include_fundamental=include_fundamental,
                force_refresh=force_refresh,
                technical_days=technical_days,
            )
            rows.append(row)
            LOGGER.info(
                "Xong %s | final=%s | F=%s V=%s T=%s R=%s | eligible=%s",
                symbol, row.get("final_score"), row.get("fundamental_score"), row.get("valuation_score"),
                row.get("technical_score"), row.get("risk_score"), row.get("eligible"),
            )
        except Exception as exc:
            LOGGER.exception("Lỗi khi xử lý %s", symbol)
            error_row = make_stock_row(symbol, None, None, error=str(exc))
            error_row["eligible"] = False
            rows.append(error_row)
            errors.append({"symbol": symbol, "error": str(exc)})
            if looks_like_rate_limit(exc):
                if stop_on_rate_limit:
                    LOGGER.warning("Dừng batch vì gặp rate limit ở %s", symbol)
                    break
                LOGGER.warning("Gặp rate limit, nghỉ %.0f giây rồi tiếp tục", rate_limit_sleep)
                time.sleep(rate_limit_sleep)

        if index < len(unique_symbols) and delay_seconds > 0:
            time.sleep(delay_seconds)

    rows.sort(key=_ranking_key, reverse=True)
    eligible_counter = 0
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        if row.get("eligible"):
            eligible_counter += 1
            row["eligible_rank"] = eligible_counter

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"stock_screening_{timestamp}.csv"
    json_path = output_dir / f"stock_screening_{timestamp}.json"
    write_csv(csv_path, rows)
    save_json(json_path, {
        "success": True,
        "engine_version": "2.0",
        "started_at": started_at,
        "generated_at": now_iso(),
        "symbols": unique_symbols,
        "count": len(rows),
        "eligible_count": eligible_counter,
        "include_fundamental": include_fundamental,
        "delay_seconds": delay_seconds,
        "errors": errors,
        "rows": rows,
    })

    LOGGER.info("Đã lưu CSV: %s", csv_path.resolve())
    LOGGER.info("Đã lưu JSON: %s", json_path.resolve())
    return {
        "success": True,
        "count": len(rows),
        "eligible_count": eligible_counter,
        "csv_path": str(csv_path.resolve()),
        "json_path": str(json_path.resolve()),
        "errors": errors,
        "top": rows[:10],
        "generated_at": now_iso(),
    }


def print_top_table(rows: List[Dict[str, Any]], limit: int = 10) -> None:
    if not rows:
        print("Không có dữ liệu.")
        return
    print("\nTOP CỔ PHIẾU - MULTI-FACTOR SCORE V2")
    print("-" * 118)
    print(f"{'#':>2} {'Mã':<6} {'Final':>6} {'Fund':>6} {'Val':>6} {'Tech':>6} {'Risk':>6} {'Grade':>5} {'OK':>3}  Hành động")
    print("-" * 118)
    for row in rows[:limit]:
        print(
            f"{str(row.get('rank') or ''):>2} {str(row.get('symbol') or ''):<6} "
            f"{str(row.get('final_score') or ''):>6} {str(row.get('fundamental_score') or ''):>6} "
            f"{str(row.get('valuation_score') or ''):>6} {str(row.get('technical_score') or ''):>6} "
            f"{str(row.get('risk_score') or ''):>6} {str(row.get('grade') or ''):>5} "
            f"{('Y' if row.get('eligible') else 'N'):>3}  {str(row.get('action') or '')}"
        )
    print("-" * 118)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stock_analyze v2 - multi-factor stock screening")
    parser.add_argument("--symbols", type=str, default=None, help="Danh sách mã, ví dụ FPT,VCB,VNM")
    parser.add_argument("--universe", type=str, default=None, help=f"Nhóm mã: {', '.join(sorted(UNIVERSES))}")
    parser.add_argument("--limit", type=int, default=None, help="Giới hạn số mã để test")
    parser.add_argument("--output-dir", type=str, default="batch_results")
    parser.add_argument("--delay", type=float, default=6.0)
    parser.add_argument("--rate-limit-sleep", type=float, default=65.0)
    parser.add_argument("--stop-on-rate-limit", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--no-fundamental", action="store_true")
    parser.add_argument("--technical-days", type=int, default=260, help="Khuyến nghị >=260 để EMA200 ổn định")
    parser.add_argument("--cache-hours-technical", type=float, default=6.0)
    parser.add_argument("--cache-hours-fundamental", type=float, default=168.0)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--verbose", action="store_true")
    return parser


def resolve_symbols(args: argparse.Namespace) -> List[str]:
    symbols = parse_symbols(args.symbols)
    if args.universe:
        symbols.extend(get_universe(args.universe))
    if not symbols:
        symbols = ["FPT", "VCB", "VNM"]
    unique: List[str] = []
    seen = set()
    for symbol in symbols:
        s = normalize_symbol(symbol)
        if s and s not in seen:
            unique.append(s)
            seen.add(s)
    if args.limit is not None and args.limit > 0:
        unique = unique[: args.limit]
    return unique


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    setup_logging(args.verbose)
    symbols = resolve_symbols(args)
    result = collect_many(
        symbols=symbols,
        output_dir=Path(args.output_dir),
        include_fundamental=not args.no_fundamental,
        delay_seconds=args.delay,
        force_refresh=args.force_refresh,
        technical_days=args.technical_days,
        cache_hours_technical=args.cache_hours_technical,
        cache_hours_fundamental=args.cache_hours_fundamental,
        stop_on_rate_limit=args.stop_on_rate_limit,
        rate_limit_sleep=args.rate_limit_sleep,
    )
    data = load_json(Path(result["json_path"])) or {}
    print_top_table(data.get("rows", []), limit=args.top)
    print(f"\nJSON: {result['json_path']}")
    print(f"CSV : {result['csv_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
