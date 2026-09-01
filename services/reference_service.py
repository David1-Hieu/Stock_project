from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,10}$")


def _clean(items: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for item in items:
        if item is None:
            continue

        text = str(item).strip().upper()
        if not text or text in {"NAN", "NONE", "NULL"}:
            continue

        # Avoid accidentally treating company names / descriptions as symbols.
        if not _SYMBOL_RE.fullmatch(text):
            continue

        if text not in seen:
            seen.add(text)
            result.append(text)

    return result


def _extract_symbols(value: Any) -> list[str]:
    """Extract ticker symbols from common vnstock response shapes."""
    if value is None:
        return []

    if isinstance(value, pd.Series):
        return _clean(value.tolist())

    if isinstance(value, pd.DataFrame):
        if value.empty:
            return []

        lower = {str(col).strip().lower(): col for col in value.columns}

        for candidate in (
            "symbol",
            "ticker",
            "code",
            "stock_code",
            "ticker_code",
            "stock_symbol",
        ):
            source = lower.get(candidate)
            if source is not None:
                symbols = _clean(value[source].tolist())
                if symbols:
                    return symbols

        # Last-resort scan, but only accept symbol-looking values.
        best: list[str] = []
        for col in value.columns:
            symbols = _clean(value[col].tolist())
            if len(symbols) > len(best):
                best = symbols
        return best

    if isinstance(value, dict):
        for candidate in (
            "symbol",
            "ticker",
            "code",
            "stock_code",
            "ticker_code",
            "stock_symbol",
        ):
            if candidate in value:
                item = value[candidate]
                if isinstance(item, (list, tuple, set, pd.Series)):
                    symbols = _clean(item)
                else:
                    symbols = _clean([item])
                if symbols:
                    return symbols

        for wrapper in ("data", "items", "results", "records", "members"):
            if wrapper in value:
                symbols = _extract_symbols(value[wrapper])
                if symbols:
                    return symbols
        return []

    if isinstance(value, (list, tuple, set)):
        items = list(value)
        if not items:
            return []

        if isinstance(items[0], dict):
            return _extract_symbols(pd.DataFrame(items))

        return _clean(items)

    if hasattr(value, "model_dump"):
        try:
            return _extract_symbols(value.model_dump())
        except Exception:
            pass

    if hasattr(value, "to_dict"):
        try:
            return _extract_symbols(value.to_dict())
        except Exception:
            pass

    return []


def _valid_members(index: str, symbols: list[str]) -> bool:
    if not symbols:
        return False

    # VN30 should contain 30 stocks. Allow a small tolerance only so a
    # temporary source-side issue does not silently pass as a valid basket.
    if index == "VN30" and len(symbols) < 25:
        return False

    return True


def get_index_members(index: str, fallback: Optional[list[str]] = None) -> list[str]:
    """
    Fetch index constituents dynamically.

    Priority:
      1. vnstock v4 Reference API, explicit KBS source
      2. vnstock v4 Reference API, VCI source
      3. legacy Listing API
      4. caller-provided static fallback
    """
    index = str(index).strip().upper()
    errors: list[str] = []

    # Current vnstock v4 Unified UI.
    try:
        from vnstock import Reference  # type: ignore

        ref = Reference()

        attempts = [
            (
                "Reference.index.members(source='kbs')",
                lambda: ref.index.members(symbol=index, source="kbs"),
            ),
            (
                "Reference.equity.list_by_group(source='kbs')",
                lambda: ref.equity.list_by_group(group=index, source="kbs"),
            ),
            (
                "Reference.index.members(source='vci')",
                lambda: ref.index.members(symbol=index, source="vci"),
            ),
            (
                "Reference.equity.list_by_group(source='vci')",
                lambda: ref.equity.list_by_group(group=index, source="vci"),
            ),
        ]

        for label, attempt in attempts:
            try:
                raw = attempt()
                symbols = _extract_symbols(raw)

                if _valid_members(index, symbols):
                    logger.info(
                        "Index %s loaded via %s: %s symbols",
                        index,
                        label,
                        len(symbols),
                    )
                    return symbols

                errors.append(
                    f"{label}: returned {len(symbols)} recognizable symbols"
                )
            except Exception as exc:
                message = f"{label}: {type(exc).__name__}: {exc}"
                errors.append(message)
                logger.warning("Index member source failed: %s", message)

    except Exception as exc:
        message = f"vnstock Reference import/init: {type(exc).__name__}: {exc}"
        errors.append(message)
        logger.warning(message)

    # Legacy vnstock API.
    try:
        from vnstock import Listing  # type: ignore

        for source in ("KBS", "VCI"):
            try:
                listing = Listing(source=source)
            except Exception:
                try:
                    listing = Listing()
                except Exception as exc:
                    errors.append(
                        f"Listing init {source}: {type(exc).__name__}: {exc}"
                    )
                    continue

            for method_name in ("symbols_by_group", "list_by_group"):
                method = getattr(listing, method_name, None)
                if method is None:
                    continue

                try:
                    raw = method(index)
                    symbols = _extract_symbols(raw)
                    if _valid_members(index, symbols):
                        logger.info(
                            "Index %s loaded via legacy Listing.%s: %s symbols",
                            index,
                            method_name,
                            len(symbols),
                        )
                        return symbols

                    errors.append(
                        f"Listing.{method_name}: returned {len(symbols)} recognizable symbols"
                    )
                except Exception as exc:
                    errors.append(
                        f"Listing.{method_name}: {type(exc).__name__}: {exc}"
                    )

    except Exception as exc:
        errors.append(f"legacy Listing import: {type(exc).__name__}: {exc}")

    if fallback:
        cleaned_fallback = _clean(fallback)
        if cleaned_fallback:
            logger.warning(
                "Could not fetch dynamic %s members; using static fallback (%s). Errors: %s",
                index,
                len(cleaned_fallback),
                " | ".join(errors),
            )
            return cleaned_fallback

    raise ValueError(
        f"Could not fetch index members for {index}. "
        f"Attempts: {' | '.join(errors) if errors else 'no usable source'}"
    )
