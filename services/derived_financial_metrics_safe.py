from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Iterable

import pandas as pd


def _norm(text: Any) -> str:
    value = "" if text is None else str(text)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_")


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            text = value.strip().replace(",", "")
            if text.lower() in {"", "n/a", "na", "none", "null", "-", "--"}:
                return None
            value = float(text)
        number = float(value)
        return number if math.isfinite(number) else None
    except Exception:
        return None


def _to_records(value: Any) -> list[dict[str, Any]]:
    """
    Read many possible statement shapes WITHOUT mutating the original payload.
    """
    if value is None:
        return []

    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")

    if isinstance(value, list):
        return [dict(x) for x in value if isinstance(x, dict)]

    if isinstance(value, tuple):
        return [dict(x) for x in value if isinstance(x, dict)]

    if isinstance(value, dict):
        # Common wrappers while preserving caller object.
        for key in ("records", "rows", "items", "data"):
            child = value.get(key)
            if isinstance(child, pd.DataFrame):
                return child.to_dict("records")
            if isinstance(child, (list, tuple)):
                rows = [dict(x) for x in child if isinstance(x, dict)]
                if rows:
                    return rows

        # Column-oriented pandas-like dict.
        try:
            df = pd.DataFrame(value)
            if not df.empty:
                return df.to_dict("records")
        except Exception:
            pass

        # Single row dictionary.
        return [dict(value)]

    return []


def _mapping(row: dict[str, Any]) -> dict[str, str]:
    return {_norm(k): k for k in row.keys()}


def _find_value(row: dict[str, Any], aliases: Iterable[str]) -> float | None:
    m = _mapping(row)
    for alias in aliases:
        key = m.get(_norm(alias))
        if key is not None:
            value = _finite(row.get(key))
            if value is not None:
                return value
    return None


def _find_text(row: dict[str, Any], aliases: Iterable[str]) -> str | None:
    m = _mapping(row)
    for alias in aliases:
        key = m.get(_norm(alias))
        if key is not None:
            value = row.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


PERIOD = ("period", "quarter", "report_period", "year", "ky", "kỳ", "nam_ky", "năm_kỳ")

REVENUE = (
    "revenue", "net_revenue", "sales", "net_sales",
    "doanh_thu", "doanh_thu_thuan", "doanh thu", "doanh thu thuần",
    "total_operating_income", "operating_income",
)
NET_INCOME = (
    "net_income", "net_profit", "profit_after_tax",
    "profit_after_tax_of_parent_company",
    "loi_nhuan_sau_thue", "loi_nhuan_rong",
    "lợi nhuận sau thuế", "lợi nhuận ròng", "ln_rong", "ln ròng",
)
GROSS_PROFIT = (
    "gross_profit", "gross_income",
    "loi_nhuan_gop", "lợi nhuận gộp", "ln_gop", "ln gộp",
)
LIABILITIES = (
    "total_liabilities", "liabilities", "total_liability",
    "tong_no_phai_tra", "tong_no", "tổng nợ phải trả", "tổng nợ",
)
EQUITY = (
    "equity", "total_equity", "owners_equity", "shareholders_equity",
    "von_chu_so_huu", "vốn chủ sở hữu",
)
CURRENT_ASSETS = (
    "current_assets", "total_current_assets", "tai_san_ngan_han", "tài sản ngắn hạn",
)
CURRENT_LIABILITIES = (
    "current_liabilities", "total_current_liabilities", "no_ngan_han", "nợ ngắn hạn",
)
CFO = (
    "cfo", "operating_cash_flow", "cash_flow_from_operating_activities",
    "net_cash_from_operating_activities", "net_cash_flow_from_operating_activities",
)
CAPEX = (
    "capex", "capital_expenditure", "capital_expenditures",
    "purchase_of_fixed_assets", "purchase_of_property_plant_equipment",
)


def _ratio(a: float | None, b: float | None, scale: float = 1.0) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b * scale


def _growth(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return (a / b - 1.0) * 100.0


def _period_key(row: dict[str, Any]) -> tuple[int, int | None] | None:
    text = _find_text(row, PERIOD)
    if not text:
        return None
    s = text.upper().replace(" ", "")

    for pat in (
        r"(?P<y>20\d{2})[-_/]?Q(?P<q>[1-4])",
        r"Q(?P<q>[1-4])[-_/]?(?P<y>20\d{2})",
    ):
        m = re.search(pat, s)
        if m:
            return int(m.group("y")), int(m.group("q"))

    m = re.fullmatch(r"(20\d{2})", s)
    if m:
        return int(m.group(1)), None
    return None


def _first_numeric(rows: list[dict[str, Any]], aliases: Iterable[str]) -> float | None:
    for row in rows:
        value = _find_value(row, aliases)
        if value is not None:
            return value
    return None


def calculate_derived_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    """
    Calculate metrics from a fundamental summary without changing any existing
    statement object (`income`, `balance`, `cash_flow`, `ratios`) or its type.
    """
    if not isinstance(summary, dict):
        return {}

    income = _to_records(summary.get("income"))
    balance = _to_records(summary.get("balance"))
    cash = _to_records(summary.get("cash_flow"))

    latest_income = income[0] if income else {}
    latest_balance = balance[0] if balance else {}
    latest_cash = cash[0] if cash else {}

    revenue = _find_value(latest_income, REVENUE)
    net_income = _find_value(latest_income, NET_INCOME)
    gross_profit = _find_value(latest_income, GROSS_PROFIT)

    liabilities = _find_value(latest_balance, LIABILITIES)
    equity = _find_value(latest_balance, EQUITY)
    current_assets = _find_value(latest_balance, CURRENT_ASSETS)
    current_liabilities = _find_value(latest_balance, CURRENT_LIABILITIES)

    cfo = _find_value(latest_cash, CFO)
    capex = _find_value(latest_cash, CAPEX)
    fcf = None if cfo is None or capex is None else cfo - abs(capex)

    result: dict[str, Any] = {
        "debt_equity": _ratio(liabilities, equity),
        "current_ratio": _ratio(current_assets, current_liabilities),
        "net_margin": _ratio(net_income, revenue, 100.0),
        "gross_margin": _ratio(gross_profit, revenue, 100.0),
        "cfo_net_income": _ratio(cfo, net_income),
        "free_cash_flow": fcf,
        "fcf_margin": _ratio(fcf, revenue, 100.0),
        "revenue_qoq": None,
        "profit_qoq": None,
        "revenue_yoy": None,
        "profit_yoy": None,
    }

    by_period = {
        key: row
        for row in income
        if (key := _period_key(row)) is not None
    }

    current_key = _period_key(latest_income)
    if current_key is not None:
        year, quarter = current_key

        if quarter is not None:
            previous_key = (year - 1, 4) if quarter == 1 else (year, quarter - 1)
            yoy_key = (year - 1, quarter)
        else:
            previous_key = (year - 1, None)
            yoy_key = (year - 1, None)

        previous = by_period.get(previous_key)
        if previous:
            result["revenue_qoq"] = _growth(
                revenue, _find_value(previous, REVENUE)
            )
            result["profit_qoq"] = _growth(
                net_income, _find_value(previous, NET_INCOME)
            )

        prior_year = by_period.get(yoy_key)
        if prior_year:
            result["revenue_yoy"] = _growth(
                revenue, _find_value(prior_year, REVENUE)
            )
            result["profit_yoy"] = _growth(
                net_income, _find_value(prior_year, NET_INCOME)
            )

    # If period parsing failed, newest->older fallback is allowed ONLY for QoQ.
    elif len(income) >= 2:
        prev = income[1]
        result["revenue_qoq"] = _growth(revenue, _find_value(prev, REVENUE))
        result["profit_qoq"] = _growth(net_income, _find_value(prev, NET_INCOME))

    return result


def enrich_fundamental_summary_safe(summary: dict[str, Any]) -> dict[str, Any]:
    """
    SAFE enrichment:
      - shallow-copy top-level summary
      - NEVER replace or reshape income/balance/cash_flow/ratios
      - only add `derived_metrics`
      - fill missing top-level derived fields
    """
    if not isinstance(summary, dict):
        return summary

    result = dict(summary)
    metrics = calculate_derived_metrics(summary)

    result["derived_metrics"] = metrics

    for key, value in metrics.items():
        existing = _finite(result.get(key))
        if existing is None and value is not None:
            result[key] = value
        elif key not in result:
            result[key] = value

    return result
