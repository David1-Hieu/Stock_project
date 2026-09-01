from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from data.providers.dnse_provider import DNSEMarketDataProvider
from data.providers.vnstock_provider import VnstockMarketDataProvider

logger = logging.getLogger(__name__)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
INDEX_SYMBOLS = {"VNINDEX", "VN30", "VN100", "HNXINDEX", "HNX30", "UPCOMINDEX"}
DAILY_INTERVALS = {"1D", "D", "DAY", "DAILY"}


class MarketDataService:
    """
    Hybrid market-data routing.

    Routing policy
    --------------
    - Intraday / realtime-oriented candles: DNSE primary, Vnstock fallback.
    - Daily index candles: DNSE primary, Vnstock fallback.
    - Daily equity candles: Vnstock primary, DNSE fallback.

    Why?
    ----
    DNSE is the preferred source for live/intraday market data and index data.
    For historical EOD equity candles, the project uses Vnstock first because
    a real FPT sample on 2026-08-28 showed DNSE /price/ohlc returning a close
    and volume that differed from the issuer's published EOD figures.
    """

    def __init__(self) -> None:
        # Kept for backward compatibility / diagnostics.
        self.primary_name = os.getenv("MARKET_DATA_PRIMARY", "dnse").strip().lower()

        self.intraday_primary = os.getenv(
            "MARKET_DATA_INTRADAY_PRIMARY", "dnse"
        ).strip().lower()

        self.eod_stock_primary = os.getenv(
            "MARKET_DATA_EOD_STOCK_PRIMARY", "vnstock"
        ).strip().lower()

        self.eod_index_primary = os.getenv(
            "MARKET_DATA_EOD_INDEX_PRIMARY", "dnse"
        ).strip().lower()

        self.dnse = DNSEMarketDataProvider()
        self.vnstock = VnstockMarketDataProvider()

    @staticmethod
    def _is_daily(interval: str) -> bool:
        return str(interval).strip().upper() in DAILY_INTERVALS

    @staticmethod
    def _is_index(symbol: str) -> bool:
        return str(symbol).strip().upper() in INDEX_SYMBOLS

    def _providers_from_name(self, primary: str):
        if primary == "vnstock":
            return [self.vnstock, self.dnse]
        return [self.dnse, self.vnstock]

    def _provider_order(self, symbol: str, interval: str):
        symbol = str(symbol).strip().upper()

        if not self._is_daily(interval):
            return self._providers_from_name(self.intraday_primary), "intraday"

        if self._is_index(symbol):
            return self._providers_from_name(self.eod_index_primary), "eod_index"

        return self._providers_from_name(self.eod_stock_primary), "eod_stock"

    def get_ohlcv(
        self,
        symbol: str,
        days: int = 180,
        interval: str = "1D",
    ) -> pd.DataFrame:
        if not symbol or not str(symbol).strip():
            raise ValueError("symbol must not be empty")

        symbol = str(symbol).strip().upper()
        requested_rows = max(int(days), 1)

        end_date = datetime.now(VN_TZ).date()

        # Give providers enough calendar range to return requested trading rows.
        calendar_days = max(requested_rows * 3, requested_rows + 60)
        start_date = end_date - timedelta(days=calendar_days)

        providers, route = self._provider_order(symbol, interval)

        errors: list[str] = []

        for provider in providers:
            if not provider.is_available():
                errors.append(f"{provider.name}: unavailable")
                continue

            try:
                df = provider.get_ohlcv(
                    symbol,
                    start_date,
                    end_date,
                    interval=interval,
                )

                if df is None or df.empty:
                    raise ValueError("provider returned empty dataframe")

                # Preserve the more specific source before standardizing provider.
                provider_detail = df.attrs.get("provider", provider.name)

                df = df.tail(requested_rows).reset_index(drop=True)

                # Normalize daily candles to trade-date semantics.
                if self._is_daily(interval) and "date" in df.columns:
                    dt = pd.to_datetime(df["date"], errors="coerce")
                    # Keep pandas Timestamp for compatibility, but remove arbitrary
                    # 07:00/09:00 source-specific time components.
                    df["date"] = dt.dt.normalize()

                df.attrs["provider"] = provider.name
                df.attrs["provider_detail"] = provider_detail
                df.attrs["route"] = route

                logger.info(
                    "OHLCV %s interval=%s via route=%s provider=%s rows=%s",
                    symbol,
                    interval,
                    route,
                    provider.name,
                    len(df),
                )
                return df

            except Exception as exc:
                errors.append(
                    f"{provider.name}: {type(exc).__name__}: {exc}"
                )
                logger.warning(
                    "Provider %s failed for %s interval=%s: %s",
                    provider.name,
                    symbol,
                    interval,
                    exc,
                )

        raise ValueError(
            f"Could not fetch OHLCV for {symbol} interval={interval}. "
            + " | ".join(errors)
        )

    def audit_daily_equity(
        self,
        symbol: str,
        days: int = 10,
    ) -> pd.DataFrame:
        """
        Compare DNSE and Vnstock daily equity bars without changing routing.

        Returns matched dates with close/volume differences. This is a manual
        data-quality tool and is intentionally NOT run on every production call.
        """
        symbol = str(symbol).strip().upper()

        if self._is_index(symbol):
            raise ValueError("audit_daily_equity is for equities, not indices")

        requested_rows = max(int(days), 2)
        end_date = datetime.now(VN_TZ).date()
        start_date = end_date - timedelta(days=max(requested_rows * 3, 60))

        frames: dict[str, pd.DataFrame] = {}
        errors: list[str] = []

        for provider in (self.dnse, self.vnstock):
            if not provider.is_available():
                errors.append(f"{provider.name}: unavailable")
                continue

            try:
                df = provider.get_ohlcv(
                    symbol,
                    start_date,
                    end_date,
                    interval="1D",
                ).copy()

                if df.empty:
                    raise ValueError("empty dataframe")

                df["trade_date"] = pd.to_datetime(
                    df["date"], errors="coerce"
                ).dt.date

                df = (
                    df[["trade_date", "close", "volume"]]
                    .dropna(subset=["trade_date", "close"])
                    .drop_duplicates("trade_date", keep="last")
                    .tail(requested_rows)
                )

                frames[provider.name] = df

            except Exception as exc:
                errors.append(
                    f"{provider.name}: {type(exc).__name__}: {exc}"
                )

        if "dnse" not in frames or "vnstock" not in frames:
            raise ValueError(
                "Need both DNSE and Vnstock for audit. " + " | ".join(errors)
            )

        merged = frames["dnse"].merge(
            frames["vnstock"],
            on="trade_date",
            how="inner",
            suffixes=("_dnse", "_vnstock"),
        )

        if merged.empty:
            raise ValueError("No overlapping daily bars between providers")

        merged["close_diff"] = (
            merged["close_dnse"] - merged["close_vnstock"]
        )
        merged["close_diff_pct"] = (
            merged["close_diff"] / merged["close_vnstock"] * 100
        )

        merged["volume_diff"] = (
            merged["volume_dnse"] - merged["volume_vnstock"]
        )
        merged["volume_diff_pct"] = (
            merged["volume_diff"] / merged["volume_vnstock"].replace(0, pd.NA) * 100
        )

        return merged.sort_values("trade_date").reset_index(drop=True)


@lru_cache(maxsize=1)
def get_market_data_service() -> MarketDataService:
    return MarketDataService()
