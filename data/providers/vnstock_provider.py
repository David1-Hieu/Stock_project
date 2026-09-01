from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterable, Optional

import pandas as pd

from .base import MarketDataProvider

logger = logging.getLogger(__name__)


def _normalize_name(name: Any) -> str:
    return str(name).strip().lower().replace(" ", "_").replace("-", "_")


def _find_column(df: pd.DataFrame, candidates: Iterable[str], contains: Iterable[str] = ()) -> Optional[str]:
    normalized_map = {_normalize_name(col): col for col in df.columns}
    for candidate in candidates:
        key = _normalize_name(candidate)
        if key in normalized_map:
            return normalized_map[key]
    for norm_name, original_name in normalized_map.items():
        if any(token.lower() in norm_name for token in contains):
            return original_name
    return None


def _standardize(raw_df: pd.DataFrame, source: str) -> pd.DataFrame:
    if raw_df is None or raw_df.empty:
        raise ValueError(f"Nguồn {source} trả về dữ liệu rỗng")

    df = raw_df.copy()
    col_map = {
        "date": _find_column(df, ["date", "time", "trading_date", "datetime", "timestamp"], ["date", "time"]),
        "open": _find_column(df, ["open", "open_price", "price_open", "o"], ["open"]),
        "high": _find_column(df, ["high", "high_price", "price_high", "h"], ["high"]),
        "low": _find_column(df, ["low", "low_price", "price_low", "l"], ["low"]),
        "close": _find_column(df, ["close", "close_price", "price_close", "adj_close", "c", "match_price"], ["close", "match"]),
        "volume": _find_column(df, ["volume", "vol", "trading_volume", "match_volume", "total_volume", "v"], ["volume", "vol"]),
    }
    missing = [k for k, v in col_map.items() if v is None]
    if missing:
        raise ValueError(f"Nguồn {source} thiếu cột {missing}; có: {list(df.columns)}")

    result = pd.DataFrame(
        {
            "date": pd.to_datetime(df[col_map["date"]], errors="coerce"),
            "open": pd.to_numeric(df[col_map["open"]], errors="coerce"),
            "high": pd.to_numeric(df[col_map["high"]], errors="coerce"),
            "low": pd.to_numeric(df[col_map["low"]], errors="coerce"),
            "close": pd.to_numeric(df[col_map["close"]], errors="coerce"),
            "volume": pd.to_numeric(df[col_map["volume"]], errors="coerce"),
        }
    )
    result = result.dropna(subset=["date", "open", "high", "low", "close"])
    result = result.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    if result.empty:
        raise ValueError(f"Nguồn {source} không còn dữ liệu hợp lệ sau chuẩn hoá")
    result.attrs["provider"] = source
    return result


class VnstockMarketDataProvider(MarketDataProvider):
    name = "vnstock"

    def __init__(self, sources: Optional[list[str]] = None) -> None:
        # TCBS đã không còn là lựa chọn ổn định trong vnstock mới; ưu tiên KBS/VCI.
        self.sources = sources or ["KBS", "VCI"]

    @staticmethod
    def _quote(symbol: str, source: str):
        try:
            from vnstock import Quote  # type: ignore

            return Quote(symbol=symbol, source=source)
        except Exception:
            from vnstock import Vnstock  # type: ignore

            return Vnstock().stock(symbol=symbol, source=source).quote

    def get_ohlcv(self, symbol: str, start: date, end: date, interval: str = "1D") -> pd.DataFrame:
        errors: list[str] = []
        symbol = symbol.strip().upper()
        for source in self.sources:
            try:
                quote = self._quote(symbol, source)
                raw = quote.history(
                    start=start.strftime("%Y-%m-%d"),
                    end=end.strftime("%Y-%m-%d"),
                    interval=interval,
                )
                return _standardize(raw, f"vnstock:{source}")
            except Exception as exc:
                errors.append(f"{source}: {type(exc).__name__}: {exc}")
                logger.warning("Vnstock %s lỗi cho %s: %s", source, symbol, exc)
        raise ValueError(f"Không lấy được OHLCV {symbol} từ Vnstock: {' | '.join(errors)}")
