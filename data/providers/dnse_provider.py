from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, time
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from .base import MarketDataProvider

logger = logging.getLogger(__name__)
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
INDEX_SYMBOLS = {"VNINDEX", "VN30", "VN100", "HNXINDEX", "HNX30", "UPCOMINDEX"}


def _to_epoch(day: date, at_end: bool = False) -> int:
    t = time(23, 59, 59) if at_end else time(0, 0, 0)
    return int(datetime.combine(day, t, tzinfo=VN_TZ).timestamp())


def _json_loads_if_possible(value: Any) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def _as_payload(body: Any) -> Any:
    """Normalize SDK response bodies.

    The DNSE OpenAPI SDK may return response body as a JSON string rather than
    a Python dict. This function accepts dict/list/JSON string/Pydantic-like
    objects/response-like objects and converts them to plain Python objects.
    """
    body = _json_loads_if_possible(body)

    if isinstance(body, (dict, list)):
        return body

    if hasattr(body, "json"):
        try:
            return _json_loads_if_possible(body.json())
        except Exception:
            pass

    if hasattr(body, "model_dump"):
        try:
            return _json_loads_if_possible(body.model_dump())
        except Exception:
            pass

    if hasattr(body, "dict"):
        try:
            return _json_loads_if_possible(body.dict())
        except Exception:
            pass

    if hasattr(body, "text"):
        try:
            return _json_loads_if_possible(body.text)
        except Exception:
            pass

    return body


def _unwrap_data(payload: Any) -> Any:
    """Unwrap one or more common {'data': ...} envelopes."""
    current = payload
    for _ in range(4):
        current = _json_loads_if_possible(current)
        if isinstance(current, dict) and "data" in current:
            nested = _json_loads_if_possible(current["data"])
            # Only unwrap if it is actually a structured payload.
            if isinstance(nested, (dict, list)):
                current = nested
                continue
        break
    return current


def _records_from_body(body: Any) -> pd.DataFrame:
    payload = _unwrap_data(_as_payload(body))

    aliases = {
        "date": ["t", "time", "timestamp", "date", "datetime"],
        "open": ["o", "open"],
        "high": ["h", "high"],
        "low": ["l", "low"],
        "close": ["c", "close"],
        "volume": ["v", "volume", "vol"],
    }

    def pick(obj: Any, keys: Iterable[str]) -> Any:
        if not isinstance(obj, dict):
            return None
        lower_map = {str(k).lower(): k for k in obj.keys()}
        for key in keys:
            actual = lower_map.get(key.lower())
            if actual is not None:
                return obj[actual]
        return None

    # Shape A: synchronized arrays, e.g. {t:[...], o:[...], h:[...], ...}
    arrays = {name: pick(payload, keys) for name, keys in aliases.items()}
    required = ["date", "open", "high", "low", "close"]
    if all(isinstance(arrays[name], (list, tuple)) for name in required):
        lengths = [len(arrays[name]) for name in required]
        if len(set(lengths)) != 1:
            raise ValueError(f"DNSE OHLC arrays have different lengths: {lengths}")
        size = lengths[0]
        volume = arrays["volume"]
        if not isinstance(volume, (list, tuple)) or len(volume) != size:
            volume = [0] * size
        df = pd.DataFrame(
            {
                "date": arrays["date"],
                "open": arrays["open"],
                "high": arrays["high"],
                "low": arrays["low"],
                "close": arrays["close"],
                "volume": volume,
            }
        )
    else:
        # Shape B: list of row dicts, directly or inside common keys.
        rows = None
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            for key in ("data", "items", "bars", "records", "result", "results"):
                value = _json_loads_if_possible(payload.get(key))
                if isinstance(value, list):
                    rows = value
                    break
        if rows is None:
            keys = list(payload.keys()) if isinstance(payload, dict) else []
            body_type = type(body).__name__
            preview = str(body)[:220].replace("\n", " ")
            raise ValueError(
                f"Unrecognized DNSE OHLC response: type={body_type}, keys={keys}, preview={preview!r}"
            )

        df = pd.DataFrame(rows)
        if df.empty:
            raise ValueError("DNSE returned an empty OHLC list")

        lower = {str(c).lower(): c for c in df.columns}
        column_map: dict[str, str] = {}
        for target, keys in aliases.items():
            for key in keys:
                source = lower.get(key.lower())
                if source is not None:
                    column_map[target] = source
                    break

        missing_required = [name for name in required if name not in column_map]
        if missing_required:
            raise ValueError(
                f"DNSE response missing OHLC columns {missing_required}; columns={list(df.columns)}"
            )
        if "volume" not in column_map:
            df["__volume__"] = 0
            column_map["volume"] = "__volume__"

        df = df.rename(columns={source: target for target, source in column_map.items()})[
            ["date", "open", "high", "low", "close", "volume"]
        ]

    numeric_dates = pd.to_numeric(df["date"], errors="coerce")
    if not numeric_dates.dropna().empty and numeric_dates.notna().mean() > 0.8:
        median = float(numeric_dates.dropna().median())
        unit = "ms" if median > 10_000_000_000 else "s"
        parsed_date = pd.to_datetime(numeric_dates, unit=unit, errors="coerce", utc=True)
        parsed_date = parsed_date.dt.tz_convert(VN_TZ).dt.tz_localize(None)
    else:
        parsed_date = pd.to_datetime(df["date"], errors="coerce")
        if getattr(parsed_date.dt, "tz", None) is not None:
            parsed_date = parsed_date.dt.tz_convert(VN_TZ).dt.tz_localize(None)

    result = pd.DataFrame(
        {
            "date": parsed_date,
            "open": pd.to_numeric(df["open"], errors="coerce"),
            "high": pd.to_numeric(df["high"], errors="coerce"),
            "low": pd.to_numeric(df["low"], errors="coerce"),
            "close": pd.to_numeric(df["close"], errors="coerce"),
            "volume": pd.to_numeric(df["volume"], errors="coerce").fillna(0),
        }
    )
    result = result.dropna(subset=["date", "open", "high", "low", "close"])
    result = result.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    if result.empty:
        raise ValueError("DNSE returned empty OHLCV after normalization")

    result.attrs["provider"] = "dnse"
    return result


class DNSEMarketDataProvider(MarketDataProvider):
    name = "dnse"

    def __init__(self) -> None:
        self.api_key = os.getenv("DNSE_API_KEY", "").strip()
        self.api_secret = os.getenv("DNSE_API_SECRET", "").strip()
        self.base_url = os.getenv("DNSE_BASE_URL", "https://openapi.dnse.com.vn").strip()
        self.api_version = os.getenv("DNSE_API_VERSION", "2026-07-23").strip()

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _client(self):
        if not self.is_available():
            raise RuntimeError("DNSE_API_KEY/DNSE_API_SECRET are not configured")

        from dnse import DNSEClient  # dnse-sdk-openapi

        return DNSEClient(
            api_key=self.api_key,
            api_secret=self.api_secret,
            base_url=self.base_url,
            api_version=self.api_version,
        )

    @staticmethod
    def _resolution(interval: str) -> str:
        value = str(interval).upper().strip()
        mapping = {
            "D": "1D",
            "1D": "1D",
            "DAY": "1D",
            "1H": "1H",
            "60M": "1H",
            "60": "1H",
            "30M": "30",
            "15M": "15",
            "5M": "5",
            "3M": "3",
            "1M": "1",
            "W": "1W",
            "1W": "1W",
        }
        return mapping.get(value, value)

    def get_ohlcv(self, symbol: str, start: date, end: date, interval: str = "1D") -> pd.DataFrame:
        symbol = symbol.strip().upper()
        query = {
            "symbol": symbol,
            "resolution": self._resolution(interval),
            "from": _to_epoch(start),
            "to": _to_epoch(end, at_end=True),
        }
        client = self._client()

        # Do not retry index symbols as STOCK. DNSE correctly rejects that as invalid symbol.
        bar_type = "INDEX" if symbol in INDEX_SYMBOLS else "STOCK"
        try:
            try:
                status, body = client.get_ohlc(bar_type, query, dry_run=False)
            except TypeError:
                status, body = client.get_ohlc(bar_type, query)

            if int(status) != 200:
                raise RuntimeError(f"HTTP {status}: {body}")
            return _records_from_body(body)
        except Exception as exc:
            logger.warning("DNSE OHLC %s (%s) failed: %s", symbol, bar_type, exc)
            raise ValueError(f"Could not fetch OHLCV {symbol} from DNSE: {type(exc).__name__}: {exc}") from exc
