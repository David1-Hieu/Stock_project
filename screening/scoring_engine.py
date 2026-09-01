"""Multi-factor stock scoring engine for Vietnamese equities.

This module is intentionally independent from vnstock/network calls.  It receives
already-normalized ``technical`` and ``fundamental`` dictionaries produced by the
existing project and converts them into four explainable component scores:

- Fundamental quality: business quality and growth.
- Valuation: P/E and P/B, with simple industry profiles.
- Technical: trend, momentum, EMA structure, RSI and active signals.
- Risk: a *safety* score (higher is safer) using leverage, balance-sheet and
  market-risk proxies available in the current project.

The engine keeps data collection separate from decision rules, making it easy to
backtest and later add VNIndex/VN30 market-regime or PhoBERT news sentiment.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "scoring_config.json"

# Lightweight symbol mapping for the current repo universes.  It is a baseline,
# not a substitute for a dynamic exchange/industry master table.
INDUSTRY_SYMBOLS: Dict[str, set[str]] = {
    "BANK": {"VCB", "BID", "CTG", "TCB", "MBB", "ACB", "STB", "VPB", "HDB", "VIB", "TPB", "SHB"},
    "SECURITIES": {"SSI", "VND", "VCI", "HCM", "MBS", "SHS", "FTS"},
    "REAL_ESTATE": {"VHM", "VIC", "VRE", "NVL", "KDH", "DXG", "PDR", "NLG", "DIG", "KBC", "SZC"},
}


def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            cleaned = value.strip().replace(",", "").replace("%", "")
            if cleaned.lower() in {"", "none", "null", "nan", "n/a", "không có dữ liệu"}:
                return None
            value = cleaned
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    except Exception:
        return None


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def get_nested(data: Mapping[str, Any] | None, path: Sequence[str], default: Any = None) -> Any:
    current: Any = data or {}
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return default
        current = current[key]
    return current


def latest_ratio(fundamental: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    ratios = get_nested(fundamental, ["ratios"], [])
    if isinstance(ratios, list) and ratios and isinstance(ratios[0], dict):
        return ratios[0]
    return {}


def latest_income(fundamental: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    income = get_nested(fundamental, ["income"], [])
    if isinstance(income, list) and income and isinstance(income[0], dict):
        return income[0]
    return {}


def recent_valid(items: Iterable[Mapping[str, Any]], key: str) -> Optional[float]:
    for item in items:
        value = safe_float(item.get(key))
        if value is not None:
            return value
    return None


def load_config(path: Optional[Path | str] = None) -> Dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {
        "version": "2.0-fallback",
        "weights": {"fundamental": 0.30, "valuation": 0.25, "technical": 0.25, "risk": 0.20},
        "grades": {"A": 80, "B": 65, "C": 50, "D": 0},
        "hard_filters": {
            "enabled": True,
            "require_positive_eps": True,
            "require_positive_net_income": True,
            "require_minimum_data": True,
            "minimum_available_components": 3,
        },
        "industry_profiles": {
            "DEFAULT": {
                "pe_weight": 0.65,
                "pb_weight": 0.35,
                "pe_good": 12,
                "pe_fair": 20,
                "pb_good": 2.0,
                "pb_fair": 3.5,
            }
        },
    }


def normalize_weights(weights: Mapping[str, Any]) -> Dict[str, float]:
    keys = ("fundamental", "valuation", "technical", "risk")
    parsed = {key: max(0.0, safe_float(weights.get(key)) or 0.0) for key in keys}
    total = sum(parsed.values())
    if total <= 0:
        return {"fundamental": 0.30, "valuation": 0.25, "technical": 0.25, "risk": 0.20}
    return {key: value / total for key, value in parsed.items()}


def infer_industry(symbol: str, explicit_industry: Optional[str] = None) -> str:
    if explicit_industry:
        value = str(explicit_industry).strip().upper()
        if value:
            return value
    symbol = str(symbol or "").strip().upper()
    for industry, members in INDUSTRY_SYMBOLS.items():
        if symbol in members:
            return industry
    return "DEFAULT"


def grade_from_score(score: Optional[float], config: Optional[Dict[str, Any]] = None) -> str:
    value = safe_float(score)
    if value is None:
        return "D"
    cfg = config or load_config()
    grades = cfg.get("grades", {}) if isinstance(cfg, dict) else {}
    thresholds = {
        "A": safe_float(grades.get("A")) or 80,
        "B": safe_float(grades.get("B")) or 65,
        "C": safe_float(grades.get("C")) or 50,
    }
    if value >= thresholds["A"]:
        return "A"
    if value >= thresholds["B"]:
        return "B"
    if value >= thresholds["C"]:
        return "C"
    return "D"


def _band_score(value: Optional[float], bands: Sequence[Tuple[float, float]]) -> float:
    """Return the score for the first upper-bound band where value <= bound."""
    if value is None:
        return 0.0
    for upper, score in bands:
        if value <= upper:
            return float(score)
    return float(bands[-1][1]) if bands else 0.0


def score_fundamental_quality(fundamental: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Score business quality/growth only; deliberately excludes valuation."""
    ratio = latest_ratio(fundamental)
    income_list = get_nested(fundamental, ["income"], [])
    income = latest_income(fundamental)
    if not isinstance(income_list, list):
        income_list = []

    roe = safe_float(ratio.get("roe"))
    roa = safe_float(ratio.get("roa"))
    net_margin = safe_float(ratio.get("net_margin"))
    eps = safe_float(ratio.get("eps"))
    revenue_growth = safe_float(income.get("revenue_growth_yoy"))
    profit_growth = safe_float(income.get("profit_growth_yoy"))
    if revenue_growth is None:
        revenue_growth = recent_valid(income_list, "revenue_growth_yoy")
    if profit_growth is None:
        profit_growth = recent_valid(income_list, "profit_growth_yoy")

    points: Dict[str, float] = {}
    reasons: List[str] = []
    warnings: List[str] = []

    if roe is None:
        points["roe"] = 0
        warnings.append("Thiếu ROE")
    elif roe >= 20:
        points["roe"] = 20
        reasons.append(f"ROE cao {roe:.1f}%")
    elif roe >= 15:
        points["roe"] = 17
        reasons.append(f"ROE tốt {roe:.1f}%")
    elif roe >= 10:
        points["roe"] = 11
    elif roe > 0:
        points["roe"] = 5
    else:
        points["roe"] = 0
        warnings.append("ROE không dương")

    if roa is None:
        points["roa"] = 0
        warnings.append("Thiếu ROA")
    elif roa >= 10:
        points["roa"] = 15
        reasons.append(f"ROA tốt {roa:.1f}%")
    elif roa >= 7:
        points["roa"] = 12
    elif roa >= 4:
        points["roa"] = 8
    elif roa > 0:
        points["roa"] = 4
    else:
        points["roa"] = 0

    if revenue_growth is None:
        points["revenue_growth"] = 0
        warnings.append("Thiếu tăng trưởng doanh thu YoY")
    elif revenue_growth >= 25:
        points["revenue_growth"] = 20
        reasons.append(f"Doanh thu YoY tăng mạnh {revenue_growth:.1f}%")
    elif revenue_growth >= 15:
        points["revenue_growth"] = 17
    elif revenue_growth >= 5:
        points["revenue_growth"] = 11
    elif revenue_growth >= 0:
        points["revenue_growth"] = 6
    else:
        points["revenue_growth"] = 0
        warnings.append(f"Doanh thu YoY giảm {abs(revenue_growth):.1f}%")

    if profit_growth is None:
        points["profit_growth"] = 0
        warnings.append("Thiếu tăng trưởng lợi nhuận YoY")
    elif profit_growth >= 30:
        points["profit_growth"] = 20
        reasons.append(f"Lợi nhuận YoY tăng mạnh {profit_growth:.1f}%")
    elif profit_growth >= 20:
        points["profit_growth"] = 17
    elif profit_growth >= 5:
        points["profit_growth"] = 11
    elif profit_growth >= 0:
        points["profit_growth"] = 5
    else:
        points["profit_growth"] = 0
        warnings.append(f"Lợi nhuận YoY giảm {abs(profit_growth):.1f}%")

    if net_margin is None:
        points["net_margin"] = 0
        warnings.append("Thiếu biên lợi nhuận ròng")
    elif net_margin >= 20:
        points["net_margin"] = 15
        reasons.append(f"Biên LN ròng cao {net_margin:.1f}%")
    elif net_margin >= 12:
        points["net_margin"] = 12
    elif net_margin >= 7:
        points["net_margin"] = 8
    elif net_margin > 0:
        points["net_margin"] = 4
    else:
        points["net_margin"] = 0

    if eps is None:
        points["eps"] = 0
        warnings.append("Thiếu EPS")
    elif eps > 0:
        points["eps"] = 10
        reasons.append("EPS dương")
    else:
        points["eps"] = 0
        warnings.append("EPS không dương")

    score = clamp(sum(points.values()))
    available = sum(value is not None for value in (roe, roa, revenue_growth, profit_growth, net_margin, eps))
    return {
        "score": round(score, 2),
        "breakdown": points,
        "reasons": reasons,
        "warnings": warnings,
        "available_metrics": available,
        "metrics": {
            "roe": roe,
            "roa": roa,
            "revenue_growth_yoy": revenue_growth,
            "profit_growth_yoy": profit_growth,
            "net_margin": net_margin,
            "eps": eps,
        },
    }


def _multiple_score(value: Optional[float], good: float, fair: float) -> float:
    """Score valuation multiples. Negative values are treated as non-meaningful."""
    if value is None or value <= 0:
        return 0.0
    if value <= good * 0.70:
        return 100.0
    if value <= good:
        return 90.0
    if value <= fair:
        # linearly decline from 90 to 60
        span = max(fair - good, 1e-9)
        return 90.0 - ((value - good) / span) * 30.0
    if value <= fair * 1.5:
        span = max(fair * 0.5, 1e-9)
        return 60.0 - ((value - fair) / span) * 35.0
    return 15.0


def score_valuation(
    symbol: str,
    fundamental: Optional[Dict[str, Any]],
    industry: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = config or load_config()
    ratio = latest_ratio(fundamental)
    pe = safe_float(ratio.get("pe"))
    pb = safe_float(ratio.get("pb"))
    industry_name = infer_industry(symbol, industry)
    profiles = cfg.get("industry_profiles", {}) if isinstance(cfg, dict) else {}
    profile = profiles.get(industry_name) or profiles.get("DEFAULT") or {}

    pe_weight = safe_float(profile.get("pe_weight")) or 0.65
    pb_weight = safe_float(profile.get("pb_weight")) or 0.35
    total_w = pe_weight + pb_weight
    if total_w <= 0:
        pe_weight, pb_weight, total_w = 0.65, 0.35, 1.0
    pe_weight /= total_w
    pb_weight /= total_w

    pe_good = safe_float(profile.get("pe_good")) or 12.0
    pe_fair = safe_float(profile.get("pe_fair")) or 20.0
    pb_good = safe_float(profile.get("pb_good")) or 2.0
    pb_fair = safe_float(profile.get("pb_fair")) or 3.5

    pe_score = _multiple_score(pe, pe_good, pe_fair)
    pb_score = _multiple_score(pb, pb_good, pb_fair)

    # Renormalize when one multiple is unavailable rather than forcing a zero.
    available: List[Tuple[float, float]] = []
    if pe is not None and pe > 0:
        available.append((pe_weight, pe_score))
    if pb is not None and pb > 0:
        available.append((pb_weight, pb_score))
    if available:
        denominator = sum(w for w, _ in available)
        score = sum(w * s for w, s in available) / denominator
    else:
        score = 0.0

    reasons: List[str] = []
    warnings: List[str] = []
    if pe is not None and pe > 0:
        reasons.append(f"P/E {pe:.2f}x")
    else:
        warnings.append("P/E thiếu hoặc không có ý nghĩa")
    if pb is not None and pb > 0:
        reasons.append(f"P/B {pb:.2f}x")
    else:
        warnings.append("P/B thiếu hoặc không có ý nghĩa")

    return {
        "score": round(clamp(score), 2),
        "industry_profile": industry_name,
        "breakdown": {"pe": round(pe_score, 2), "pb": round(pb_score, 2)},
        "weights": {"pe": round(pe_weight, 4), "pb": round(pb_weight, 4)},
        "metrics": {"pe": pe, "pb": pb},
        "reasons": reasons,
        "warnings": warnings,
        "available_metrics": len(available),
    }


def _signal_active(signals: Mapping[str, Any], name: str) -> bool:
    item = signals.get(name)
    return bool(isinstance(item, Mapping) and item.get("active"))


def score_technical(technical: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    indicators = get_nested(technical, ["indicators"], {}) or {}
    signals = get_nested(technical, ["signals"], {}) or {}
    trend = str(get_nested(technical, ["trend"], "")).strip().upper()

    last_price = safe_float(get_nested(technical, ["last_price"]))
    rsi = safe_float(indicators.get("rsi"))
    macd = safe_float(indicators.get("macd"))
    macd_signal = safe_float(indicators.get("macd_signal"))
    macd_hist = safe_float(indicators.get("macd_hist"))
    ema20 = safe_float(indicators.get("ema20"))
    ema50 = safe_float(indicators.get("ema50"))
    ema200 = safe_float(indicators.get("ema200"))

    points: Dict[str, float] = {"trend": 0, "ema_structure": 0, "rsi": 0, "macd": 0, "signals": 0, "volume": 0}
    reasons: List[str] = []
    warnings: List[str] = []

    if trend == "TĂNG":
        points["trend"] = 25
        reasons.append("Xu hướng trung hạn tăng")
    elif trend == "SIDEWAY":
        points["trend"] = 13
    elif trend == "GIẢM":
        points["trend"] = 4
        warnings.append("Xu hướng trung hạn giảm")

    if all(v is not None for v in (last_price, ema20, ema50, ema200)):
        assert last_price is not None and ema20 is not None and ema50 is not None and ema200 is not None
        if last_price > ema20 > ema50 > ema200:
            points["ema_structure"] = 20
            reasons.append("Giá > EMA20 > EMA50 > EMA200")
        elif last_price > ema20 and ema50 > ema200:
            points["ema_structure"] = 15
        elif last_price > ema200:
            points["ema_structure"] = 10
        elif last_price < ema20 < ema50 < ema200:
            points["ema_structure"] = 0
            warnings.append("Cấu trúc EMA giảm rõ")
        else:
            points["ema_structure"] = 6
    else:
        warnings.append("Thiếu dữ liệu EMA")

    if rsi is None:
        warnings.append("Thiếu RSI")
    elif 45 <= rsi <= 65:
        points["rsi"] = 15
        reasons.append(f"RSI cân bằng/tích cực {rsi:.1f}")
    elif 35 <= rsi < 45 or 65 < rsi <= 72:
        points["rsi"] = 10
    elif 30 <= rsi < 35 or 72 < rsi <= 80:
        points["rsi"] = 6
    else:
        points["rsi"] = 3
        warnings.append(f"RSI cực trị {rsi:.1f}")

    if macd_hist is not None:
        if macd_hist > 0:
            points["macd"] = 16
            reasons.append("MACD histogram dương")
            if macd is not None and macd_signal is not None and macd > macd_signal:
                points["macd"] = 20
        else:
            points["macd"] = 5
    elif macd is not None and macd_signal is not None:
        points["macd"] = 16 if macd > macd_signal else 5
    else:
        warnings.append("Thiếu MACD")

    if isinstance(signals, Mapping):
        signal_points = 0.0
        if _signal_active(signals, "macd_bullish_cross"):
            signal_points += 5
            reasons.append("MACD bullish cross")
        if _signal_active(signals, "golden_cross"):
            signal_points += 5
            reasons.append("Golden cross")
        if _signal_active(signals, "macd_bearish_cross"):
            signal_points -= 4
            warnings.append("MACD bearish cross")
        if _signal_active(signals, "death_cross"):
            signal_points -= 6
            warnings.append("Death cross")
        points["signals"] = clamp(signal_points, 0, 10)

        if _signal_active(signals, "volume_spike"):
            points["volume"] = 10
            reasons.append("Khối lượng đột biến")
        else:
            points["volume"] = 5

    score = clamp(sum(points.values()))
    available = sum(v is not None for v in (rsi, macd_hist if macd_hist is not None else macd, ema20, ema50, ema200))
    return {
        "score": round(score, 2),
        "breakdown": points,
        "metrics": {
            "trend": trend or None,
            "rsi": rsi,
            "macd": macd,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
        },
        "reasons": reasons,
        "warnings": warnings,
        "available_metrics": available,
    }


def score_risk(technical: Optional[Dict[str, Any]], fundamental: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a safety score 0-100. Higher means lower observed risk.

    The current source project does not expose a full return series in the batch
    summary.  Therefore v2 uses leverage/balance-sheet and technical-volatility
    proxies.  A later phase can replace these proxies with beta, realized
    volatility and max drawdown without changing the public output schema.
    """
    ratio = latest_ratio(fundamental)
    income = latest_income(fundamental)
    balance = get_nested(fundamental, ["balance"], {}) or {}
    indicators = get_nested(technical, ["indicators"], {}) or {}

    debt_equity = safe_float(ratio.get("debt_equity"))
    net_income = safe_float(income.get("net_income"))
    total_debt = safe_float(balance.get("total_debt"))
    total_assets = safe_float(balance.get("total_assets"))
    cash = safe_float(balance.get("cash"))
    last_price = safe_float(get_nested(technical, ["last_price"]))
    ema200 = safe_float(indicators.get("ema200"))
    rsi = safe_float(indicators.get("rsi"))
    bb_upper = safe_float(indicators.get("bb_upper"))
    bb_lower = safe_float(indicators.get("bb_lower"))
    bb_mid = safe_float(indicators.get("bb_mid"))

    points: Dict[str, float] = {"leverage": 0, "debt_assets": 0, "profitability": 0, "trend_risk": 0, "momentum_risk": 0, "volatility_proxy": 0}
    reasons: List[str] = []
    warnings: List[str] = []

    if debt_equity is None:
        points["leverage"] = 10  # neutral instead of zero for missing data
        warnings.append("Thiếu Debt/Equity")
    elif debt_equity < 0.5:
        points["leverage"] = 25
        reasons.append("Đòn bẩy thấp")
    elif debt_equity <= 1.0:
        points["leverage"] = 21
    elif debt_equity <= 1.5:
        points["leverage"] = 15
    elif debt_equity <= 2.0:
        points["leverage"] = 9
    else:
        points["leverage"] = 3
        warnings.append(f"Debt/Equity cao {debt_equity:.2f}x")

    debt_assets = None
    if total_debt is not None and total_assets not in (None, 0):
        debt_assets = total_debt / total_assets
    if debt_assets is None:
        points["debt_assets"] = 8
    elif debt_assets <= 0.35:
        points["debt_assets"] = 20
        reasons.append("Tỷ lệ nợ/tài sản thấp")
    elif debt_assets <= 0.55:
        points["debt_assets"] = 15
    elif debt_assets <= 0.70:
        points["debt_assets"] = 9
    else:
        points["debt_assets"] = 3
        warnings.append("Tỷ lệ nợ/tài sản cao")

    if net_income is None:
        points["profitability"] = 7
    elif net_income > 0:
        points["profitability"] = 15
    else:
        points["profitability"] = 0
        warnings.append("Lợi nhuận ròng kỳ gần nhất không dương")

    if last_price is not None and ema200 is not None and ema200 != 0:
        distance = (last_price - ema200) / ema200 * 100
        if distance >= 0:
            points["trend_risk"] = 15
        elif distance >= -10:
            points["trend_risk"] = 9
        else:
            points["trend_risk"] = 3
            warnings.append("Giá thấp hơn EMA200 đáng kể")
    else:
        points["trend_risk"] = 7

    if rsi is None:
        points["momentum_risk"] = 5
    elif 35 <= rsi <= 70:
        points["momentum_risk"] = 10
    elif 25 <= rsi < 35 or 70 < rsi <= 80:
        points["momentum_risk"] = 6
    else:
        points["momentum_risk"] = 2
        warnings.append("Momentum ở vùng cực trị")

    bb_width = None
    if bb_upper is not None and bb_lower is not None and bb_mid not in (None, 0):
        bb_width = (bb_upper - bb_lower) / abs(bb_mid)
    if bb_width is None:
        points["volatility_proxy"] = 7
    elif bb_width <= 0.10:
        points["volatility_proxy"] = 15
    elif bb_width <= 0.20:
        points["volatility_proxy"] = 12
    elif bb_width <= 0.35:
        points["volatility_proxy"] = 8
    else:
        points["volatility_proxy"] = 3
        warnings.append("Biên Bollinger rộng, biến động ngắn hạn cao")

    score = clamp(sum(points.values()))
    return {
        "score": round(score, 2),
        "meaning": "Điểm càng cao = mức an toàn quan sát được càng tốt",
        "breakdown": points,
        "metrics": {
            "debt_equity": debt_equity,
            "debt_assets": round(debt_assets, 4) if debt_assets is not None else None,
            "net_income": net_income,
            "cash": cash,
            "bb_width": round(bb_width, 4) if bb_width is not None else None,
        },
        "reasons": reasons,
        "warnings": warnings,
        "available_metrics": sum(v is not None for v in (debt_equity, debt_assets, net_income, last_price, ema200, rsi, bb_width)),
    }


def apply_hard_filters(
    fundamental: Optional[Dict[str, Any]],
    component_scores: Mapping[str, Mapping[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = config or load_config()
    rules = cfg.get("hard_filters", {}) if isinstance(cfg, dict) else {}
    if not rules.get("enabled", True):
        return {"eligible": True, "reasons": [], "warnings": []}

    ratio = latest_ratio(fundamental)
    income = latest_income(fundamental)
    eps = safe_float(ratio.get("eps"))
    net_income = safe_float(income.get("net_income"))
    reasons: List[str] = []
    warnings: List[str] = []

    if rules.get("require_positive_eps", True) and eps is not None and eps <= 0:
        reasons.append("EPS không dương")
    elif eps is None:
        warnings.append("Không kiểm tra được EPS do thiếu dữ liệu")

    if rules.get("require_positive_net_income", True) and net_income is not None and net_income <= 0:
        reasons.append("Lợi nhuận ròng kỳ gần nhất không dương")
    elif net_income is None:
        warnings.append("Không kiểm tra được lợi nhuận ròng do thiếu dữ liệu")

    if rules.get("require_minimum_data", True):
        minimum = int(safe_float(rules.get("minimum_available_components")) or 3)
        available_components = sum(
            1 for name in ("fundamental", "valuation", "technical", "risk")
            if safe_float(get_nested(component_scores.get(name), ["score"])) is not None
            and int(get_nested(component_scores.get(name), ["available_metrics"], 0) or 0) > 0
        )
        if available_components < minimum:
            reasons.append(f"Thiếu dữ liệu: chỉ có {available_components}/4 nhóm điểm đủ thông tin")

    return {"eligible": len(reasons) == 0, "reasons": reasons, "warnings": warnings}


def _action_from_score(score: float, eligible: bool) -> str:
    if not eligible:
        return "LOẠI/THẬN TRỌNG"
    if score >= 80:
        return "ƯU TIÊN PHÂN TÍCH"
    if score >= 65:
        return "THEO DÕI"
    if score >= 50:
        return "TRUNG LẬP"
    return "THẬN TRỌNG"


def score_stock(
    symbol: str,
    technical: Optional[Dict[str, Any]],
    fundamental: Optional[Dict[str, Any]],
    *,
    industry: Optional[str] = None,
    config_path: Optional[Path | str] = None,
) -> Dict[str, Any]:
    """Compute the full v2 score for one stock."""
    cfg = load_config(config_path)
    weights = normalize_weights(cfg.get("weights", {}))

    fundamental_result = score_fundamental_quality(fundamental)
    valuation_result = score_valuation(symbol, fundamental, industry=industry, config=cfg)
    technical_result = score_technical(technical)
    risk_result = score_risk(technical, fundamental)

    components: Dict[str, Dict[str, Any]] = {
        "fundamental": fundamental_result,
        "valuation": valuation_result,
        "technical": technical_result,
        "risk": risk_result,
    }

    weighted = {
        name: round((safe_float(result.get("score")) or 0.0) * weights[name], 4)
        for name, result in components.items()
    }
    raw_score = clamp(sum(weighted.values()))
    filters = apply_hard_filters(fundamental, components, config=cfg)
    eligible = bool(filters.get("eligible"))

    # Do not destroy the diagnostic score when a stock fails a hard filter.
    # Ranking will put ineligible stocks behind eligible names.
    grade = grade_from_score(raw_score, cfg)

    positives: List[str] = []
    negatives: List[str] = []
    for result in components.values():
        positives.extend(str(x) for x in result.get("reasons", [])[:2])
        negatives.extend(str(x) for x in result.get("warnings", [])[:2])
    negatives.extend(str(x) for x in filters.get("reasons", []))

    return {
        "version": str(cfg.get("version", "2.0")),
        "symbol": str(symbol).strip().upper(),
        "final_score": round(raw_score, 2),
        "grade": grade,
        "eligible": eligible,
        "action": _action_from_score(raw_score, eligible),
        "weights": {k: round(v, 4) for k, v in weights.items()},
        "weighted_contribution": weighted,
        "components": components,
        "filters": filters,
        "explanation": {
            "positive": positives[:6],
            "negative": negatives[:6],
            "summary": (
                f"{str(symbol).strip().upper()} đạt {raw_score:.1f}/100, hạng {grade}. "
                f"Fundamental {fundamental_result['score']:.1f}, Valuation {valuation_result['score']:.1f}, "
                f"Technical {technical_result['score']:.1f}, Risk {risk_result['score']:.1f}."
            ),
        },
    }
