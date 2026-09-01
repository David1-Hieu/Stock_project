from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Iterable, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class VnstockDataFundamentalService:
    """Ưu tiên vnstock_data (nếu đã cài/gói tài trợ), fallback vnstock community."""

    METHOD_MAP = {
        "ratio": ["ratio", "ratios"],
        "income": ["income_statement", "income", "income_statement_report"],
        "balance": ["balance_sheet", "balance", "balance_sheet_report", "balance_sheet_statement"],
        "cash_flow": ["cash_flow", "cashflow", "cash_flow_statement", "cash_flow_report"],
    }

    def _from_vnstock_data(self, symbol: str, table_type: str, period: str, lang: str) -> pd.DataFrame:
        from vnstock_data import Fundamental  # type: ignore

        fun = Fundamental()
        equity = fun.equity(symbol)
        method_name = {
            "ratio": "ratio",
            "income": "income_statement",
            "balance": "balance_sheet",
            "cash_flow": "cash_flow",
        }[table_type]
        method = getattr(equity, method_name)

        # format='wide' dùng Semantic ID làm cột và tương thích tốt với parser hiện tại hơn long format.
        call_variants = [
            {"period": period, "lang": lang, "format": "wide", "drop_empty": True},
            {"period": period, "lang": lang, "format": "time_series", "drop_empty": True},
            {"period": period, "lang": lang},
        ]
        last_error: Optional[Exception] = None
        for kwargs in call_variants:
            try:
                df = method(**kwargs)
                if isinstance(df, pd.DataFrame) and not df.empty:
                    return df
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        return pd.DataFrame()

    @staticmethod
    def _get_legacy_finance(symbol: str, source: str):
        try:
            from vnstock import Finance  # type: ignore

            return Finance(symbol=symbol, source=source)
        except Exception:
            from vnstock import Vnstock  # type: ignore

            return Vnstock().stock(symbol=symbol, source=source).finance

    @staticmethod
    def _call_legacy(finance: Any, names: Iterable[str], period: str, lang: str) -> pd.DataFrame:
        variants = [period]
        if period == "year":
            variants.extend(["Y", "annual"])
        elif period == "quarter":
            variants.append("Q")
        last_error: Optional[Exception] = None
        for name in names:
            method = getattr(finance, name, None)
            if method is None:
                continue
            for p in variants:
                for kwargs in ({"period": p, "lang": lang}, {"period": p}, {"lang": lang}, {}):
                    try:
                        df = method(**kwargs)
                        if isinstance(df, pd.DataFrame) and not df.empty:
                            return df
                    except Exception as exc:
                        last_error = exc
        if last_error:
            raise last_error
        return pd.DataFrame()

    def load_table(self, symbol: str, table_type: str, period: str, lang: str = "vi") -> pd.DataFrame:
        symbol = symbol.strip().upper()
        if table_type not in self.METHOD_MAP:
            raise ValueError(f"table_type không hợp lệ: {table_type}")

        try:
            df = self._from_vnstock_data(symbol, table_type, period, lang)
            if not df.empty:
                df.attrs["provider"] = "vnstock_data"
                return df
        except Exception as exc:
            logger.info("vnstock_data %s %s chưa dùng được: %s", table_type, symbol, exc)

        # Community fallback. Không còn dựa vào TCBS.
        source_order = ["VCI", "KBS"] if table_type in {"balance", "cash_flow"} else ["KBS", "VCI"]
        errors: list[str] = []
        for source in source_order:
            try:
                finance = self._get_legacy_finance(symbol, source)
                df = self._call_legacy(finance, self.METHOD_MAP[table_type], period, lang)
                if not df.empty:
                    df.attrs["provider"] = f"vnstock:{source}"
                    return df
            except Exception as exc:
                errors.append(f"{source}: {type(exc).__name__}: {exc}")
        logger.warning("Không lấy được %s %s: %s", table_type, symbol, " | ".join(errors))
        return pd.DataFrame()


@lru_cache(maxsize=1)
def get_fundamental_data_service() -> VnstockDataFundamentalService:
    return VnstockDataFundamentalService()


def load_finance_table(symbol: str, table_type: str, period: str, lang: str = "vi") -> pd.DataFrame:
    return get_fundamental_data_service().load_table(symbol, table_type, period, lang)
