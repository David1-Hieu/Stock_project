from __future__ import annotations

import json

from services.market_data_service import get_market_data_service
from services.reference_service import get_index_members


def _show(service, symbol: str, interval: str = "1D", days: int = 40) -> None:
    try:
        df = service.get_ohlcv(symbol, days=days, interval=interval)
        print(
            symbol,
            interval,
            "rows=", len(df),
            "provider=", df.attrs.get("provider"),
            "detail=", df.attrs.get("provider_detail"),
            "route=", df.attrs.get("route"),
            "last=", df.tail(1).to_dict("records"),
        )
    except Exception as exc:
        print(symbol, interval, "ERROR", type(exc).__name__, exc)


def main() -> None:
    service = get_market_data_service()

    print("MARKET_DATA_PRIMARY:", service.primary_name)
    print("DNSE available:", service.dnse.is_available())
    print("EOD stock primary:", service.eod_stock_primary)
    print("EOD index primary:", service.eod_index_primary)
    print("Intraday primary:", service.intraday_primary)

    # Expected:
    # VNINDEX 1D -> DNSE
    # VN30    1D -> DNSE
    # FPT     1D -> Vnstock
    _show(service, "VNINDEX", "1D", 40)
    _show(service, "VN30", "1D", 40)
    _show(service, "FPT", "1D", 40)

    try:
        members = get_index_members("VN30", fallback=[])
        print(
            "VN30 members:",
            len(members),
            json.dumps(members, ensure_ascii=False),
        )
    except Exception as exc:
        print("VN30 members ERROR", type(exc).__name__, exc)

    try:
        audit = service.audit_daily_equity("FPT", days=5)
        print("FPT EOD audit:")
        print(audit.tail().to_string(index=False))
    except Exception as exc:
        print("FPT audit ERROR", type(exc).__name__, exc)

    try:
        from fundamental import get_fundamental_summary

        data = get_fundamental_summary("FPT")
        print("Fundamental keys:", sorted(data.keys()))
        print("Cash flow rows:", len(data.get("cash_flow") or []))
    except Exception as exc:
        print("Fundamental ERROR", type(exc).__name__, exc)


if __name__ == "__main__":
    main()
