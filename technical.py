"""
Module phân tích kỹ thuật cho dự án AI Agent chứng khoán Việt Nam.

Chức năng chính:
- Lấy dữ liệu OHLCV từ vnstock với nhiều nguồn fallback.
- Tính RSI, MACD, Bollinger Bands, EMA và trung bình khối lượng.
- Phát hiện tín hiệu kỹ thuật cơ bản.
- Xuất summary và dữ liệu chart cho dashboard/agent.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd


from services.market_data_service import get_market_data_service
# =========================
# Cấu hình chung
# =========================
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DEFAULT_SOURCES = ["VCI", "TCBS", "KBS"]

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


# =========================
# Helper functions nội bộ
# =========================
def _normalize_col_name(name: Any) -> str:
    """Chuẩn hoá tên cột để dò tìm linh hoạt."""
    return str(name).strip().lower().replace(" ", "_").replace("-", "_")


def _find_column(df: pd.DataFrame, candidates: List[str], contains: Optional[List[str]] = None) -> Optional[str]:
    """Tìm tên cột thật trong DataFrame dựa trên danh sách tên ứng viên."""
    normalized_map = {_normalize_col_name(col): col for col in df.columns}

    for candidate in candidates:
        key = _normalize_col_name(candidate)
        if key in normalized_map:
            return normalized_map[key]

    if contains:
        for norm_name, original_name in normalized_map.items():
            if any(token.lower() in norm_name for token in contains):
                return original_name

    return None


def _safe_float(value: Any) -> Optional[float]:
    """Chuyển giá trị sang float an toàn để tránh lỗi JSON/NaN."""
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value: Any, digits: int = 2) -> Optional[float]:
    """Làm tròn số nếu có thể, ngược lại trả về None."""
    value = _safe_float(value)
    return round(value, digits) if value is not None else None


def _format_date(value: Any) -> str:
    """Format ngày về dạng YYYY-MM-DD."""
    try:
        return pd.to_datetime(value).strftime("%Y-%m-%d")
    except Exception:
        return str(value)


def _get_vnstock_quote(symbol: str, source: str):
    """
    Tạo Quote object từ vnstock.

    Ưu tiên dùng class Quote theo yêu cầu dự án. Nếu phiên bản vnstock đang cài
    thay đổi API, fallback sang giao diện Vnstock().stock(...).quote.
    """
    try:
        from vnstock import Quote  # type: ignore

        return Quote(symbol=symbol, source=source)
    except Exception as quote_error:
        logger.warning("Không khởi tạo được Quote(%s, %s): %s", symbol, source, quote_error)

    try:
        from vnstock import Vnstock  # type: ignore

        return Vnstock().stock(symbol=symbol, source=source).quote
    except Exception as stock_error:
        logger.warning("Không khởi tạo được Vnstock().stock(%s, %s).quote: %s", symbol, source, stock_error)
        raise stock_error


def _standardize_ohlcv(raw_df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Chuẩn hoá DataFrame từ vnstock về các cột date/open/high/low/close/volume."""
    if raw_df is None or raw_df.empty:
        raise ValueError(f"Nguồn {source} trả về DataFrame rỗng")

    df = raw_df.copy()

    col_map = {
        "date": _find_column(
            df,
            candidates=["date", "time", "trading_date", "tradingDate", "datetime", "timestamp"],
            contains=["date", "time"],
        ),
        "open": _find_column(df, candidates=["open", "open_price", "price_open", "o"], contains=["open"]),
        "high": _find_column(df, candidates=["high", "high_price", "price_high", "h"], contains=["high"]),
        "low": _find_column(df, candidates=["low", "low_price", "price_low", "l"], contains=["low"]),
        "close": _find_column(
            df,
            candidates=["close", "close_price", "price_close", "adj_close", "c", "match_price"],
            contains=["close", "match"],
        ),
        "volume": _find_column(
            df,
            candidates=["volume", "vol", "trading_volume", "match_volume", "total_volume"],
            contains=["volume", "vol"],
        ),
    }

    missing = [standard_name for standard_name, real_name in col_map.items() if real_name is None]
    if missing:
        raise ValueError(
            f"Nguồn {source} thiếu cột bắt buộc: {missing}. "
            f"Các cột hiện có: {list(df.columns)}"
        )

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
    result = result.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    result = result.reset_index(drop=True)

    if result.empty:
        raise ValueError(f"Nguồn {source} không còn dữ liệu hợp lệ sau khi chuẩn hoá")

    return result


def _cross_up(series_a: pd.Series, series_b: pd.Series, lookback: int = 1) -> bool:
    """Kiểm tra series_a cắt lên series_b trong lookback nến gần nhất."""
    data = pd.DataFrame({"a": series_a, "b": series_b}).dropna().tail(lookback + 1)
    if len(data) < 2:
        return False

    for i in range(1, len(data)):
        prev = data.iloc[i - 1]
        curr = data.iloc[i]
        if prev["a"] <= prev["b"] and curr["a"] > curr["b"]:
            return True
    return False


def _cross_down(series_a: pd.Series, series_b: pd.Series, lookback: int = 1) -> bool:
    """Kiểm tra series_a cắt xuống series_b trong lookback nến gần nhất."""
    data = pd.DataFrame({"a": series_a, "b": series_b}).dropna().tail(lookback + 1)
    if len(data) < 2:
        return False

    for i in range(1, len(data)):
        prev = data.iloc[i - 1]
        curr = data.iloc[i]
        if prev["a"] >= prev["b"] and curr["a"] < curr["b"]:
            return True
    return False


# =========================
# Public functions
# =========================
def load_ohlcv(symbol: str, days: int = 180) -> pd.DataFrame:
    """
    Lấy OHLCV qua MarketDataService.

    Thứ tự mặc định: DNSE OpenAPI -> Vnstock fallback. Nếu chưa cấu hình DNSE
    thì service tự bỏ qua DNSE và dùng Vnstock, vì vậy các flow cũ vẫn chạy.
    """
    service = get_market_data_service()
    return service.get_ohlcv(symbol=symbol, days=days, interval="1D")


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tính các chỉ số kỹ thuật cho DataFrame OHLCV.

    Các indicator gồm:
    - RSI(14)
    - MACD(12,26,9): macd, macd_signal, macd_hist
    - Bollinger Bands(20,2): bb_upper, bb_mid, bb_lower
    - EMA(20), EMA(50), EMA(200)
    - Volume MA(20)

    Args:
        df: DataFrame có cột date, open, high, low, close, volume.

    Returns:
        DataFrame được thêm các cột indicator.
    """
    if df is None or df.empty:
        raise ValueError("DataFrame OHLCV rỗng, không thể tính indicator")

    required_cols = {"date", "open", "high", "low", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame thiếu cột bắt buộc: {sorted(missing)}")

    result = df.copy()
    result = result.sort_values("date").reset_index(drop=True)

    close = pd.to_numeric(result["close"], errors="coerce")
    volume = pd.to_numeric(result["volume"], errors="coerce")

    # Khởi tạo cột trước để các hàm sau không bị KeyError nếu pandas-ta đổi tên cột.
    indicator_cols = [
        "rsi",
        "macd",
        "macd_signal",
        "macd_hist",
        "bb_lower",
        "bb_mid",
        "bb_upper",
        "ema20",
        "ema50",
        "ema200",
        "volume_ma20",
    ]
    for col in indicator_cols:
        if col not in result.columns:
            result[col] = pd.NA

    def _pick_ta_column(ta_df: pd.DataFrame, startswith: str, contains: Optional[str] = None) -> Optional[str]:
        """Tìm cột pandas-ta linh hoạt vì tên có thể là BBU_20_2 hoặc BBU_20_2.0."""
        if ta_df is None or ta_df.empty:
            return None
        startswith = startswith.lower()
        contains = contains.lower() if contains else None
        for col_name in ta_df.columns:
            normalized = str(col_name).lower()
            if normalized.startswith(startswith) and (contains is None or contains in normalized):
                return col_name
        return None

    try:
        import pandas_ta as ta  # type: ignore

        rsi_series = ta.rsi(close, length=14)
        if rsi_series is not None:
            result["rsi"] = rsi_series

        macd_df = ta.macd(close, fast=12, slow=26, signal=9)
        if macd_df is not None and not macd_df.empty:
            macd_col = _pick_ta_column(macd_df, "MACD_")
            signal_col = _pick_ta_column(macd_df, "MACDs_")
            hist_col = _pick_ta_column(macd_df, "MACDh_")
            if macd_col:
                result["macd"] = macd_df[macd_col]
            if signal_col:
                result["macd_signal"] = macd_df[signal_col]
            if hist_col:
                result["macd_hist"] = macd_df[hist_col]

        bb_df = ta.bbands(close, length=20, std=2)
        if bb_df is not None and not bb_df.empty:
            lower_col = _pick_ta_column(bb_df, "BBL_")
            mid_col = _pick_ta_column(bb_df, "BBM_")
            upper_col = _pick_ta_column(bb_df, "BBU_")
            if lower_col:
                result["bb_lower"] = bb_df[lower_col]
            if mid_col:
                result["bb_mid"] = bb_df[mid_col]
            if upper_col:
                result["bb_upper"] = bb_df[upper_col]

        result["ema20"] = ta.ema(close, length=20)
        result["ema50"] = ta.ema(close, length=50)
        result["ema200"] = ta.ema(close, length=200)

    except ImportError as exc:
        raise ImportError("Chưa cài pandas-ta. Hãy chạy: pip install pandas-ta") from exc
    except Exception as exc:
        logger.warning("pandas-ta gặp lỗi, chuyển sang công thức fallback bằng pandas: %s", exc)

    # Fallback bằng pandas nếu pandas-ta không trả về đủ cột hoặc tên cột thay đổi.
    if result["rsi"].isna().all():
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).rolling(window=14, min_periods=14).mean()
        rs = gain / loss.replace(0, pd.NA)
        result["rsi"] = 100 - (100 / (1 + rs))

    if result["macd"].isna().all() or result["macd_signal"].isna().all():
        ema_fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
        ema_slow = close.ewm(span=26, adjust=False, min_periods=26).mean()
        result["macd"] = ema_fast - ema_slow
        result["macd_signal"] = result["macd"].ewm(span=9, adjust=False, min_periods=9).mean()
        result["macd_hist"] = result["macd"] - result["macd_signal"]

    if result["bb_lower"].isna().all() or result["bb_mid"].isna().all() or result["bb_upper"].isna().all():
        bb_mid = close.rolling(window=20, min_periods=20).mean()
        bb_std = close.rolling(window=20, min_periods=20).std()
        result["bb_mid"] = bb_mid
        result["bb_upper"] = bb_mid + 2 * bb_std
        result["bb_lower"] = bb_mid - 2 * bb_std

    if result["ema20"].isna().all():
        result["ema20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    if result["ema50"].isna().all():
        result["ema50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()
    if result["ema200"].isna().all():
        result["ema200"] = close.ewm(span=200, adjust=False, min_periods=200).mean()

    result["volume_ma20"] = volume.rolling(window=20, min_periods=1).mean()

    # ffill để xử lý dữ liệu bị thiếu lẻ tẻ.
    result = result.ffill()

    # Chỉ drop theo các cột thật sự cần cho summary. Không drop toàn bộ DataFrame
    # vì một cột phụ bị lỗi tên có thể khiến toàn bộ kết quả bị xoá sạch.
    essential_cols = [
        "close",
        "volume",
        "rsi",
        "macd",
        "macd_signal",
        "bb_lower",
        "bb_mid",
        "bb_upper",
        "ema20",
        "ema50",
        "ema200",
        "volume_ma20",
    ]
    result = result.dropna(subset=essential_cols).reset_index(drop=True)

    if result.empty:
        raise ValueError(
            "Không đủ dữ liệu để tính indicator, đặc biệt là EMA200. "
            "Hãy tăng tham số days, ví dụ days=300 hoặc 365"
        )

    return result

def detect_signals(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """
    Phát hiện các tín hiệu kỹ thuật từ DataFrame đã có indicator.

    Mỗi tín hiệu trả về theo format:
    {active: bool, value: float | None, description: str}

    Args:
        df: DataFrame đã được compute_indicators().

    Returns:
        Dict chứa trạng thái các tín hiệu kỹ thuật.
    """
    if df is None or df.empty:
        raise ValueError("DataFrame indicator rỗng, không thể phát hiện tín hiệu")

    latest = df.iloc[-1]
    last_close = _safe_float(latest.get("close"))
    last_rsi = _safe_float(latest.get("rsi"))
    last_macd = _safe_float(latest.get("macd"))
    last_macd_signal = _safe_float(latest.get("macd_signal"))
    last_ema20 = _safe_float(latest.get("ema20"))
    last_ema50 = _safe_float(latest.get("ema50"))
    last_ema200 = _safe_float(latest.get("ema200"))
    last_bb_upper = _safe_float(latest.get("bb_upper"))
    last_bb_lower = _safe_float(latest.get("bb_lower"))
    last_bb_mid = _safe_float(latest.get("bb_mid"))
    last_volume = _safe_float(latest.get("volume"))
    last_volume_ma20 = _safe_float(latest.get("volume_ma20"))

    macd_bullish = _cross_up(df["macd"], df["macd_signal"], lookback=1)
    macd_bearish = _cross_down(df["macd"], df["macd_signal"], lookback=1)
    golden_cross = _cross_up(df["ema50"], df["ema200"], lookback=5)
    death_cross = _cross_down(df["ema50"], df["ema200"], lookback=5)

    bb_width = None
    if last_bb_upper is not None and last_bb_lower is not None and last_bb_mid not in (None, 0):
        bb_width = (last_bb_upper - last_bb_lower) / last_bb_mid

    volume_ratio = None
    if last_volume is not None and last_volume_ma20 not in (None, 0):
        volume_ratio = last_volume / last_volume_ma20

    signals: Dict[str, Dict[str, Any]] = {
        "rsi_oversold": {
            "active": bool(last_rsi is not None and last_rsi < 30),
            "value": _round_or_none(last_rsi),
            "description": "RSI dưới 30, cổ phiếu có thể đang rơi vào vùng quá bán.",
        },
        "rsi_overbought": {
            "active": bool(last_rsi is not None and last_rsi > 70),
            "value": _round_or_none(last_rsi),
            "description": "RSI trên 70, cổ phiếu có thể đang ở vùng quá mua.",
        },
        "macd_bullish_cross": {
            "active": macd_bullish,
            "value": _round_or_none((last_macd or 0) - (last_macd_signal or 0)),
            "description": "MACD line cắt lên Signal line trong 2 nến gần nhất, tín hiệu động lượng tích cực.",
        },
        "macd_bearish_cross": {
            "active": macd_bearish,
            "value": _round_or_none((last_macd or 0) - (last_macd_signal or 0)),
            "description": "MACD line cắt xuống Signal line trong 2 nến gần nhất, tín hiệu động lượng tiêu cực.",
        },
        "price_above_ema20": {
            "active": bool(last_close is not None and last_ema20 is not None and last_close > last_ema20),
            "value": _round_or_none(last_close),
            "description": "Giá đóng cửa nằm trên EMA20, xu hướng ngắn hạn đang nghiêng về tích cực.",
        },
        "price_below_ema20": {
            "active": bool(last_close is not None and last_ema20 is not None and last_close < last_ema20),
            "value": _round_or_none(last_close),
            "description": "Giá đóng cửa nằm dưới EMA20, xu hướng ngắn hạn đang yếu hơn.",
        },
        "golden_cross": {
            "active": golden_cross,
            "value": _round_or_none((last_ema50 or 0) - (last_ema200 or 0)),
            "description": "EMA50 cắt lên EMA200 trong 5 nến gần nhất, tín hiệu xu hướng tăng trung hạn.",
        },
        "death_cross": {
            "active": death_cross,
            "value": _round_or_none((last_ema50 or 0) - (last_ema200 or 0)),
            "description": "EMA50 cắt xuống EMA200 trong 5 nến gần nhất, tín hiệu xu hướng giảm trung hạn.",
        },
        "bb_squeeze": {
            "active": bool(bb_width is not None and bb_width < 0.10),
            "value": _round_or_none(bb_width, 4),
            "description": "Bollinger Bands đang co hẹp, có thể báo hiệu giai đoạn tích luỹ trước biến động mạnh.",
        },
        "volume_spike": {
            "active": bool(volume_ratio is not None and volume_ratio > 2),
            "value": _round_or_none(volume_ratio),
            "description": "Khối lượng hiện tại lớn hơn 2 lần trung bình 20 phiên, cho thấy dòng tiền đột biến.",
        },
    }

    return signals


def get_technical_summary(symbol: str, days: int = 180) -> Dict[str, Any]:
    """
    Tạo bản tóm tắt phân tích kỹ thuật hoàn chỉnh cho một mã cổ phiếu.

    Hàm lần lượt gọi:
    load_ohlcv() -> compute_indicators() -> detect_signals().

    Args:
        symbol: Mã cổ phiếu.
        days: Số phiên dữ liệu cần phân tích.

    Returns:
        Dict gồm giá gần nhất, indicator, tín hiệu, xu hướng và thời điểm tạo.
    """
    symbol = str(symbol).strip().upper()
    df = load_ohlcv(symbol=symbol, days=days)

    # EMA200 cần nhiều dữ liệu; nếu days quá thấp thì tự lấy thêm để tính ổn định hơn.
    if days < 220:
        try:
            df_for_indicators = load_ohlcv(symbol=symbol, days=260)
        except Exception:
            df_for_indicators = df
    else:
        df_for_indicators = df

    indicator_df = compute_indicators(df_for_indicators)
    signals = detect_signals(indicator_df)
    latest = indicator_df.iloc[-1]

    ema50 = _safe_float(latest.get("ema50"))
    ema200 = _safe_float(latest.get("ema200"))
    if ema50 is not None and ema200 is not None:
        if ema50 > ema200:
            trend = "TĂNG"
        elif ema50 < ema200:
            trend = "GIẢM"
        else:
            trend = "SIDEWAY"
    else:
        trend = "SIDEWAY"

    return {
        "symbol": symbol,
        "days": days,
        "last_price": _round_or_none(latest.get("close")),
        "last_date": _format_date(latest.get("date")),
        "indicators": {
            "rsi": _round_or_none(latest.get("rsi")),
            "macd": _round_or_none(latest.get("macd")),
            "macd_signal": _round_or_none(latest.get("macd_signal")),
            "macd_hist": _round_or_none(latest.get("macd_hist")),
            "bb_upper": _round_or_none(latest.get("bb_upper")),
            "bb_mid": _round_or_none(latest.get("bb_mid")),
            "bb_lower": _round_or_none(latest.get("bb_lower")),
            "ema20": _round_or_none(latest.get("ema20")),
            "ema50": _round_or_none(latest.get("ema50")),
            "ema200": _round_or_none(latest.get("ema200")),
            "volume_ma20": _round_or_none(latest.get("volume_ma20")),
        },
        "signals": signals,
        "trend": trend,
        "generated_at": datetime.now(VN_TZ).isoformat(timespec="seconds"),
    }


def get_chart_data(symbol: str, days: int = 90) -> List[Dict[str, Any]]:
    """
    Lấy dữ liệu phục vụ biểu đồ kỹ thuật trên dashboard.

    Kết quả chỉ gồm các cột cần thiết:
    date, open, high, low, close, volume, rsi, macd, ema20, ema50.

    Args:
        symbol: Mã cổ phiếu.
        days: Số phiên gần nhất cần trả về cho chart.

    Returns:
        List of dict, mỗi phần tử là một phiên giao dịch.
    """
    symbol = str(symbol).strip().upper()
    df = load_ohlcv(symbol=symbol, days=max(days + 220, 260))
    indicator_df = compute_indicators(df)

    chart_cols = ["date", "open", "high", "low", "close", "volume", "rsi", "macd", "ema20", "ema50"]
    chart_df = indicator_df[chart_cols].dropna().tail(days).copy()
    chart_df["date"] = chart_df["date"].apply(_format_date)

    return chart_df.to_dict(orient="records")


if __name__ == "__main__":
    import json

    summary = get_technical_summary("VNM")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
