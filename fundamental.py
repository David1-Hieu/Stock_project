"""
Module phân tích cơ bản cho dự án AI Agent chứng khoán Việt Nam.

Chức năng chính:
- Lấy và chuẩn hoá báo cáo tài chính từ vnstock.
- Trích xuất P/E, P/B, ROE, ROA, EPS, Debt/Equity, biên lợi nhuận.
- Đọc kết quả kinh doanh, bảng cân đối kế toán.
- Tính điểm sức khoẻ tài chính 0-100.

Lưu ý:
- API và tên cột của vnstock có thể thay đổi theo phiên bản/nguồn dữ liệu.
- File này luôn dò tên cột linh hoạt và bắt lỗi để tránh crash toàn bộ pipeline.
"""

from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd


# =========================
# Cấu hình chung
# =========================
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DEFAULT_FINANCE_SOURCES = ["KBS", "VCI", "TCBS"]
# Cache bảng tài chính trong memory để tránh gọi lặp vnstock và giảm nguy cơ chạm rate limit.
_FINANCE_TABLE_CACHE: Dict[Tuple[str, str, str, str], pd.DataFrame] = {}

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


# =========================
# Helper functions nội bộ
# =========================
def _strip_accents(text: Any) -> str:
    """Bỏ dấu tiếng Việt để dò cột ổn định hơn."""
    text = str(text)
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def _normalize_col_name(name: Any) -> str:
    """Chuẩn hoá tên cột: lowercase, bỏ dấu, thay ký tự đặc biệt bằng dấu gạch dưới."""
    text = _strip_accents(name).lower().strip()
    text = re.sub(r"[\s\-\/\.]+", "_", text)
    text = re.sub(r"[^a-z0-9_%_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _compact_name(name: Any) -> str:
    """Chuẩn hoá tên cột thành chuỗi chữ-số liền nhau để match fuzzy."""
    return re.sub(r"[^a-z0-9]+", "", _normalize_col_name(name))


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns nếu vnstock trả về bảng có nhiều tầng cột."""
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()

    result = df.copy()
    if isinstance(result.columns, pd.MultiIndex):
        result.columns = [
            "__".join(str(part) for part in col if str(part).strip() not in {"", "nan", "None"})
            for col in result.columns
        ]
    else:
        result.columns = [str(col) for col in result.columns]

    # Nếu năm/kỳ nằm ở index thì đưa ra thành cột để dễ xử lý.
    if result.index.name is not None or not isinstance(result.index, pd.RangeIndex):
        result = result.reset_index()

    return result


def _safe_float(value: Any) -> Optional[float]:
    """Chuyển giá trị sang float an toàn, hỗ trợ chuỗi có dấu %, dấu phẩy."""
    try:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned in {"", "-", "--", "nan", "None", "N/A", "Không có dữ liệu"}:
                return None
            cleaned = cleaned.replace("%", "")
            cleaned = cleaned.replace(",", "")
            cleaned = cleaned.replace(" ", "")
            value = cleaned
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    except Exception:
        return None


def _round_or_none(value: Any, digits: int = 2) -> Optional[float]:
    """Làm tròn số nếu có thể."""
    number = _safe_float(value)
    return round(number, digits) if number is not None else None




def _normalize_debt_equity(value: Any) -> Optional[float]:
    """Chuẩn hoá Debt/Equity về đơn vị số lần.

    Một số nguồn vnstock/KBS trả Debt/Equity theo phần trăm, ví dụ 101.48
    nghĩa là khoảng 1.0148 lần. Tiêu chí chấm điểm của project dùng đơn vị
    số lần, nên cần đổi các giá trị percent-like về ratio-like.
    """
    number = _safe_float(value)
    if number is None:
        return None
    # D/E theo số lần hiếm khi vượt 20 lần đối với doanh nghiệp thông thường.
    # Nếu nguồn trả 101.48, 60.0, 250.0... thì coi là phần trăm và chia 100.
    if abs(number) > 20:
        number = number / 100
    return round(number, 2)

def _format_percent(value: Any) -> Optional[float]:
    """
    Chuẩn hoá phần trăm.

    Một số nguồn trả ROE = 0.15, nguồn khác trả 15. Nếu abs(value) <= 1.5
    thì hiểu là tỷ lệ thập phân và đổi sang phần trăm.
    """
    number = _safe_float(value)
    if number is None:
        return None
    if abs(number) <= 1.5:
        number *= 100
    return round(number, 2)


def _now_iso() -> str:
    """Trả về thời gian hiện tại theo giờ Việt Nam."""
    return datetime.now(VN_TZ).isoformat(timespec="seconds")


def _find_column(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    """Tìm cột theo danh sách ứng viên, có hỗ trợ bỏ dấu và fuzzy matching."""
    if df is None or df.empty:
        return None

    candidate_norms = {_normalize_col_name(c) for c in candidates}
    candidate_compacts = {_compact_name(c) for c in candidates}

    normalized_map = {_normalize_col_name(col): col for col in df.columns}
    compact_map = {_compact_name(col): col for col in df.columns}

    # 1) Match exact theo normalized.
    for candidate in candidate_norms:
        if candidate in normalized_map:
            return normalized_map[candidate]

    # 2) Match exact theo compact.
    for candidate in candidate_compacts:
        if candidate in compact_map:
            return compact_map[candidate]

    # 3) Match contains theo normalized/compact, ưu tiên ứng viên dài để tránh match nhầm.
    for candidate in sorted(candidate_norms, key=len, reverse=True):
        if len(candidate) < 3:
            continue
        for norm_name, original_name in normalized_map.items():
            if candidate in norm_name or norm_name in candidate:
                return original_name

    for candidate in sorted(candidate_compacts, key=len, reverse=True):
        if len(candidate) < 3:
            continue
        for compact_name, original_name in compact_map.items():
            if candidate in compact_name or compact_name in candidate:
                return original_name

    return None


def _find_metric_column(df: pd.DataFrame, aliases: Iterable[str], exclude: Iterable[str] = ()) -> Optional[str]:
    """Tìm cột chỉ tiêu tài chính theo alias, tránh các từ loại trừ."""
    if df is None or df.empty:
        return None

    exclude_compacts = {_compact_name(item) for item in exclude}
    alias_norms = [_normalize_col_name(item) for item in aliases]
    alias_compacts = [_compact_name(item) for item in aliases]

    # Ưu tiên exact/contains có kiểm soát.
    best_col: Optional[str] = None
    best_score = -1

    for col in df.columns:
        norm = _normalize_col_name(col)
        compact = _compact_name(col)

        if any(ex in compact for ex in exclude_compacts if ex):
            continue

        score = 0
        for alias_norm, alias_compact in zip(alias_norms, alias_compacts):
            if not alias_compact:
                continue

            if compact == alias_compact or norm == alias_norm:
                score = max(score, 100 + len(alias_compact))
            elif len(alias_compact) >= 3 and alias_compact in compact:
                score = max(score, 70 + len(alias_compact))
            elif len(alias_norm) >= 3 and alias_norm in norm:
                score = max(score, 60 + len(alias_norm))

        # Một số alias ngắn như PE/PB/DE cần xử lý riêng.
        tokens = set(norm.split("_"))
        if "pe" in alias_compacts and ("pe" in tokens or compact in {"pe", "peratio", "pricetoearnings"}):
            score = max(score, 90)
        if "pb" in alias_compacts and ("pb" in tokens or compact in {"pb", "pbratio", "pricetobook"}):
            score = max(score, 90)
        if "eps" in alias_compacts and ("eps" in tokens or compact == "eps"):
            score = max(score, 90)

        if score > best_score:
            best_score = score
            best_col = col

    return best_col if best_score > 0 else None


def _looks_like_period_value(value: Any) -> bool:
    """Kiểm tra một giá trị/tên cột có giống năm, quý hoặc ngày báo cáo không.

    Chú ý: không dùng pd.to_datetime bừa bãi với số thuần như 98.22 hoặc
    984376000000.0, vì pandas có thể hiểu chúng là timestamp nano giây năm
    1970 và làm nhận nhầm cột số liệu thành cột kỳ/năm.
    """
    if value is None:
        return False

    # Nếu là số thật, chỉ chấp nhận dạng năm 4 chữ số hợp lệ.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            number = float(value)
            if math.isnan(number) or math.isinf(number):
                return False
            return number.is_integer() and 1900 <= int(number) <= 2100
        except Exception:
            return False

    text = str(value).strip().lower()
    if text in {"", "nan", "none", "null"}:
        return False

    plain = _strip_accents(text).lower().strip()

    # Chuỗi số thuần: chỉ xem là kỳ nếu là năm 4 chữ số, ví dụ "2025".
    # Không parse "98.22", "4542.23", "984376000000.0" thành ngày.
    if re.fullmatch(r"[-+]?\d+(?:\.0+)?", plain):
        try:
            number = float(plain)
            return number.is_integer() and 1900 <= int(number) <= 2100
        except Exception:
            return False

    # Dạng năm 2024, 2025 hoặc chuỗi có năm.
    if re.search(r"(?:19|20)\d{2}", plain):
        return True

    # Dạng Q1/2024, quý 2 2025, quarter 3.
    if re.search(r"(?:^|[^a-z])(q[1-4]|quy\s*[1-4]|quarter\s*[1-4])", plain):
        return True

    # Chỉ parse datetime nếu chuỗi có dấu phân tách/ngữ cảnh ngày tháng rõ ràng.
    if not re.search(r"[-/]|\b(thang|month|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", plain):
        return False

    try:
        dt = pd.to_datetime(value, errors="coerce")
        if not pd.isna(dt) and 1900 <= int(dt.year) <= 2100:
            return True
    except Exception:
        pass
    return False

def _period_value_ratio(series: pd.Series) -> float:
    """Tỷ lệ giá trị trong một series trông giống kỳ/năm báo cáo."""
    if series is None or len(series) == 0:
        return 0.0
    non_null = series.dropna()
    if len(non_null) == 0:
        return 0.0
    return float(non_null.apply(_looks_like_period_value).mean())


def _get_period_column(df: pd.DataFrame) -> Optional[str]:
    """Dò cột thể hiện năm/kỳ báo cáo, tránh match nhầm cột numeric như giá trị chỉ tiêu."""
    if df is None or df.empty:
        return None

    candidates = [
        "year",
        "nam",
        "fiscal_year",
        "report_year",
        "period",
        "ky",
        "quarter",
        "quy",
        "report_period",
        "date",
        "time",
    ]
    direct = _find_column(df, candidates)
    if direct is not None and _period_value_ratio(df[direct]) >= 0.5:
        return direct

    # Nếu tên cột không rõ, chọn cột mà phần lớn giá trị là kỳ/năm.
    best_col: Optional[str] = None
    best_ratio = 0.0
    for col in df.columns:
        ratio = _period_value_ratio(df[col])
        if ratio > best_ratio:
            best_ratio = ratio
            best_col = col
    return best_col if best_ratio >= 0.6 else None


def _period_to_sort_key(value: Any) -> Tuple[int, int, str]:
    """Chuyển kỳ/năm báo cáo thành sort key giảm dần."""
    if value is None:
        return (0, 0, "")

    text = str(value).strip()
    plain = _strip_accents(text).lower().strip()
    numbers = [int(x) for x in re.findall(r"\d+", text)]

    year = 0
    quarter = 0

    for num in numbers:
        if 1900 <= num <= 2100:
            year = num
            break

    q_match = re.search(r"(?:q|quy|quarter)[^0-9]*([1-4])", plain)
    if q_match:
        quarter = int(q_match.group(1))
    elif len(numbers) >= 2:
        small_nums = [n for n in numbers if 1 <= n <= 4]
        if small_nums:
            quarter = small_nums[0]

    # Chỉ parse datetime khi chuỗi có dấu/ngữ cảnh ngày tháng rõ ràng.
    numeric_like = re.fullmatch(r"[-+]?\d+(?:\.\d+)?", plain) is not None
    date_like = re.search(r"[-/]|\b(thang|month|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", plain) is not None
    if year == 0 and not numeric_like and date_like:
        try:
            dt = pd.to_datetime(value, errors="coerce")
            if not pd.isna(dt):
                year = int(dt.year)
                quarter = int((dt.month - 1) // 3 + 1)
        except Exception:
            pass

    return (year, quarter, text)

def _sort_by_period_desc(df: pd.DataFrame) -> pd.DataFrame:
    """Sắp xếp bảng theo kỳ/năm mới nhất trước."""
    if df is None or df.empty:
        return df

    period_col = _get_period_column(df)
    result = df.copy()

    if period_col:
        result["__sort_key"] = result[period_col].apply(_period_to_sort_key)
        result = result.sort_values("__sort_key", ascending=False).drop(columns=["__sort_key"])
    else:
        result = result.iloc[::-1]

    return result.reset_index(drop=True)


def _period_named_columns(df: pd.DataFrame) -> List[str]:
    """Lấy các cột có tên giống kỳ/năm, ví dụ 2025, 2024, Q1/2025."""
    if df is None or df.empty:
        return []
    cols = [col for col in df.columns if _looks_like_period_value(col)]
    # Loại cột chứa toàn text không phải số liệu nếu có.
    return cols


def _looks_like_metric_label(value: Any) -> bool:
    """Kiểm tra giá trị có giống tên chỉ tiêu tài chính không."""
    if value is None:
        return False
    text = str(value).strip()
    if text in {"", "nan", "None", "null"}:
        return False
    if _safe_float(text) is not None:
        return False
    compact = _compact_name(text)
    keywords = [
        "pe", "pb", "roe", "roa", "eps", "bien", "margin", "doanhthu",
        "loinhuan", "laigop", "taisan", "nophaitra", "vonchusohuu",
        "tien", "equity", "assets", "liabilities", "revenue", "profit",
        "earnings", "debt", "cash", "income", "thunhap",
    ]
    return any(k in compact for k in keywords) or len(compact) >= 5


def _find_metric_label_column(df: pd.DataFrame) -> Optional[str]:
    """Tìm cột chứa tên chỉ tiêu khi vnstock trả bảng dạng dọc: chỉ tiêu x kỳ."""
    if df is None or df.empty:
        return None

    # Ưu tiên các cột thường chứa tên chỉ tiêu.
    preferred = _find_column(
        df,
        [
            "index", "item", "items", "metric", "metrics", "indicator", "indicators",
            "chi_tieu", "chỉ tiêu", "ten_chi_tieu", "name", "field", "field_name",
        ],
    )
    if preferred is not None:
        values = df[preferred].dropna()
        if len(values) and values.apply(_looks_like_metric_label).mean() >= 0.3:
            return preferred

    best_col: Optional[str] = None
    best_score = 0.0
    for col in df.columns:
        values = df[col].dropna()
        if len(values) == 0:
            continue
        # Cột metric label thường là text và không giống kỳ/năm.
        metric_score = float(values.apply(_looks_like_metric_label).mean())
        period_score = _period_value_ratio(df[col])
        score = metric_score - period_score
        if score > best_score:
            best_score = score
            best_col = col

    return best_col if best_score >= 0.25 else None


def _standardize_finance_table(df: pd.DataFrame, table_type: str) -> pd.DataFrame:
    """
    Chuẩn hoá output vnstock về dạng: mỗi dòng là một kỳ/năm, mỗi cột là một chỉ tiêu.

    Vnstock đôi khi trả bảng ngang/dọc khác nhau theo source. Trường hợp phổ biến:
    - Dòng = chỉ tiêu tài chính; cột = năm/kỳ.
    - Dòng = năm/kỳ; cột = chỉ tiêu tài chính.
    Hàm này phát hiện dạng đầu tiên và xoay lại để các hàm trích xuất phía dưới hoạt động đúng.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    result = _flatten_columns(df)
    if result.empty:
        return result

    # Nếu đã có cột period hợp lệ và nhiều cột metric thì giữ nguyên.
    period_col = _get_period_column(result)
    if period_col is not None:
        # Tránh trường hợp period_col là một cột numeric bị match nhầm: _get_period_column đã validate.
        return result

    period_cols = _period_named_columns(result)
    metric_col = _find_metric_label_column(result)

    # Nếu có >=2 cột năm/kỳ và một cột tên chỉ tiêu, xoay bảng.
    if len(period_cols) >= 2 and metric_col is not None:
        records: List[Dict[str, Any]] = []
        for period_name in period_cols:
            record: Dict[str, Any] = {"period": str(period_name)}
            for _, row in result.iterrows():
                metric_name = row.get(metric_col)
                if metric_name is None:
                    continue
                metric_text = str(metric_name).strip()
                if metric_text in {"", "nan", "None"}:
                    continue
                # Không đưa các dòng giống kỳ/năm vào tên metric.
                if _looks_like_period_value(metric_text):
                    continue
                record[metric_text] = row.get(period_name)
            records.append(record)

        standardized = pd.DataFrame(records)
        logger.info(
            "Chuẩn hoá bảng %s từ dạng chỉ tiêu x kỳ sang kỳ x chỉ tiêu: %s dòng, %s cột",
            table_type,
            len(standardized),
            len(standardized.columns),
        )
        return standardized

    return result


def _call_finance_method(finance: Any, method_names: Iterable[str], period: str, lang: str = "vi") -> pd.DataFrame:
    """
    Gọi một method của finance object, tự thử nhiều tên method/tham số.

    Vnstock các phiên bản khác nhau có thể dùng ratio/ratios hoặc tham số period/lang khác nhau.
    """
    last_error: Optional[Exception] = None

    period_variants = [period]
    if period == "year":
        period_variants += ["Y", "annual"]
    elif period == "quarter":
        period_variants += ["Q"]

    for method_name in method_names:
        method = getattr(finance, method_name, None)
        if method is None:
            continue

        for period_value in period_variants:
            call_variants = [
                {"period": period_value, "lang": lang},
                {"period": period_value},
                {"lang": lang},
                {},
            ]
            for kwargs in call_variants:
                try:
                    raw = method(**kwargs)
                    df = _flatten_columns(raw)
                    if not df.empty:
                        return df
                except TypeError as exc:
                    last_error = exc
                    continue
                except Exception as exc:
                    last_error = exc
                    logger.warning("Lỗi khi gọi finance.%s(%s): %s", method_name, kwargs, exc)
                    continue

    if last_error:
        raise last_error
    raise AttributeError(f"Không tìm thấy method phù hợp trong finance object: {list(method_names)}")


def _get_finance_object(symbol: str, source: str = "KBS") -> Any:
    """
    Tạo finance object từ vnstock.

    Ưu tiên Finance(symbol, source='KBS') theo yêu cầu dự án. Nếu API đang cài
    dùng Unified UI, fallback sang Vnstock().stock(...).finance.
    """
    try:
        from vnstock import Finance  # type: ignore

        return Finance(symbol=symbol, source=source)
    except Exception as finance_error:
        logger.warning("Không khởi tạo được Finance(%s, %s): %s", symbol, source, finance_error)

    try:
        from vnstock import Vnstock  # type: ignore

        stock = Vnstock().stock(symbol=symbol, source=source)
        return stock.finance
    except Exception as stock_error:
        logger.warning("Không khởi tạo được Vnstock().stock(%s, %s).finance: %s", symbol, source, stock_error)
        raise stock_error


def _load_finance_table(symbol: str, table_type: str, period: str, lang: str = "vi") -> pd.DataFrame:
    """
    Lấy bảng tài chính từ nhiều source fallback.

    Hàm này có cache trong memory để tránh gọi lặp lại vnstock trong cùng một lần chạy.
    Điều này đặc biệt quan trọng với bản cộng đồng vì dễ chạm giới hạn request/phút.
    """
    symbol = symbol.upper().strip()
    cache_key = (symbol, table_type, period, lang)
    if cache_key in _FINANCE_TABLE_CACHE:
        logger.info("Dùng cache %s %s period=%s", table_type, symbol, period)
        return _FINANCE_TABLE_CACHE[cache_key].copy()

    method_map = {
        "ratio": ["ratio", "ratios"],
        "income": ["income_statement", "income", "income_statement_report"],
        "balance": ["balance_sheet", "balance", "balance_sheet_report", "balance_sheet_statement"],
    }
    methods = method_map.get(table_type)
    if not methods:
        raise ValueError(f"table_type không hợp lệ: {table_type}")

    # KBS thường ổn cho ratio/income; balance trong môi trường test của bạn thành công ở VCI.
    if table_type == "balance":
        source_order = ["VCI", "KBS", "TCBS"]
    else:
        source_order = DEFAULT_FINANCE_SOURCES

    errors: List[str] = []
    for source in source_order:
        try:
            logger.info("Đang lấy %s %s từ nguồn %s", table_type, symbol, source)
            finance = _get_finance_object(symbol=symbol, source=source)
            df = _call_finance_method(finance, methods, period=period, lang=lang)
            df = _standardize_finance_table(df, table_type=table_type)
            df = _sort_by_period_desc(df)
            logger.info("Lấy %s %s thành công từ %s: %s dòng, %s cột", table_type, symbol, source, len(df), len(df.columns))
            _FINANCE_TABLE_CACHE[cache_key] = df.copy()
            return df.copy()
        except Exception as exc:
            message = f"{source}: {type(exc).__name__}: {exc}"
            errors.append(message)
            logger.exception("Lỗi khi lấy %s %s từ %s", table_type, symbol, source)

    logger.error("Không thể lấy %s cho %s. Chi tiết: %s", table_type, symbol, " | ".join(errors))
    empty_df = pd.DataFrame()
    _FINANCE_TABLE_CACHE[cache_key] = empty_df.copy()
    return empty_df


def _extract_value(row: pd.Series, df: pd.DataFrame, aliases: Iterable[str], percent: bool = False) -> Optional[float]:
    """Trích xuất một chỉ tiêu từ row theo danh sách alias."""
    col = _find_metric_column(df, aliases)
    if col is None:
        return None
    value = row.get(col)
    return _format_percent(value) if percent else _round_or_none(value)


def _get_period_value(row: pd.Series, df: pd.DataFrame) -> Any:
    """Lấy giá trị kỳ/năm từ một row."""
    period_col = _get_period_column(df)
    if period_col is not None:
        return row.get(period_col)
    return None


def _format_period(value: Any, fallback_index: Optional[int] = None) -> str:
    """Format kỳ/năm thành string dễ đọc."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return f"Kỳ {fallback_index}" if fallback_index is not None else "Không rõ kỳ"
    return str(value)


def _safe_growth(current: Any, base: Any) -> Optional[float]:
    """Tính tăng trưởng % an toàn."""
    current_num = _safe_float(current)
    base_num = _safe_float(base)
    if current_num is None or base_num is None or base_num == 0:
        return None
    return round((current_num - base_num) / abs(base_num) * 100, 2)


def _recent_valid(items: List[Dict[str, Any]], key: str) -> Optional[float]:
    """Lấy giá trị hợp lệ đầu tiên trong list dict."""
    for item in items:
        value = _safe_float(item.get(key))
        if value is not None:
            return value
    return None


def _format_money_value(value: Any) -> str:
    """Format tiền; nếu None thì trả về 'Không có dữ liệu'."""
    if value is None:
        return "Không có dữ liệu"
    return format_billion(value)


# =========================
# Public API
# =========================
def format_billion(n: Any) -> str:
    """
    Chuyển số tiền VND thành chuỗi dễ đọc.

    Quy ước:
    - 1 tỷ đồng = 1.000.000.000 đồng
    - 1 nghìn tỷ đồng = 1.000.000.000.000 đồng

    Ví dụ:
    - 1_234_567_000 -> "1.23 tỷ đ"
    - 16_169_790_000_000 -> "16.17 nghìn tỷ đ"
    """
    number = _safe_float(n)
    if number is None:
        return "Không có dữ liệu"

    sign = "-" if number < 0 else ""
    value = abs(number)

    if value >= 1_000_000_000_000:
        return f"{sign}{value / 1_000_000_000_000:.2f} nghìn tỷ đ"
    if value >= 1_000_000_000:
        return f"{sign}{value / 1_000_000_000:.2f} tỷ đ"
    if value >= 1_000_000:
        return f"{sign}{value / 1_000_000:.2f} triệu đ"
    if value >= 1_000:
        return f"{sign}{value / 1_000:.2f} nghìn đ"
    return f"{sign}{value:,.0f} đ".replace(",", ".")


def get_financial_ratios(symbol: str) -> List[Dict[str, Any]]:
    """
    Lấy và chuẩn hoá các chỉ số tài chính theo năm.

    Trả về list dict mới nhất trước, mỗi dict gồm:
    {year, pe, pb, roe, roa, debt_equity, eps, net_margin}.
    Nếu thiếu cột hoặc lỗi một field, field đó là None thay vì làm crash toàn bộ.
    """
    symbol = symbol.upper().strip()
    df = _load_finance_table(symbol=symbol, table_type="ratio", period="year", lang="vi")
    if df.empty:
        return []

    results: List[Dict[str, Any]] = []

    # Cột được dò một lần để tăng độ ổn định.
    period_col = _get_period_column(df)
    pe_col = _find_metric_column(df, ["pe", "p/e", "pe_ratio", "price_to_earnings", "gia_thi_truong_tren_thu_nhap", "thi_gia_tren_eps", "p e"])
    pb_col = _find_metric_column(df, ["pb", "p/b", "pb_ratio", "price_to_book", "gia_thi_truong_tren_gia_tri_so_sach", "thi_gia_tren_bvps", "p b"])
    roe_col = _find_metric_column(df, ["roe", "return_on_equity", "loi_nhuan_tren_von_chu_so_huu"])
    roa_col = _find_metric_column(df, ["roa", "return_on_assets", "loi_nhuan_tren_tai_san"])
    de_col = _find_metric_column(
        df,
        [
            "debt_equity",
            "debt_to_equity",
            "debt/equity",
            "d/e",
            "de",
            "no_von",
            "no_tren_von",
            "no_phai_tra_von_chu_so_huu",
            "tong_no_von_chu_so_huu",
        ],
    )
    eps_col = _find_metric_column(df, ["eps", "earnings_per_share", "lai_co_ban_tren_co_phieu", "thu_nhap_moi_co_phieu"])
    margin_col = _find_metric_column(
        df,
        [
            "net_margin",
            "profit_margin",
            "bien_loi_nhuan_rong",
            "bien_loi_nhuan_sau_thue",
            "ty_suat_loi_nhuan_rong",
            "margin",
            "bien",
        ],
    )

    for idx, row in df.iterrows():
        period_value = row.get(period_col) if period_col else None
        if period_value is None:
            period_value = _period_to_sort_key(idx)[0] or idx

        item = {
            "year": _format_period(period_value),
            "pe": _round_or_none(row.get(pe_col)) if pe_col else None,
            "pb": _round_or_none(row.get(pb_col)) if pb_col else None,
            "roe": _format_percent(row.get(roe_col)) if roe_col else None,
            "roa": _format_percent(row.get(roa_col)) if roa_col else None,
            "debt_equity": _normalize_debt_equity(row.get(de_col)) if de_col else None,
            "eps": _round_or_none(row.get(eps_col)) if eps_col else None,
            "net_margin": _format_percent(row.get(margin_col)) if margin_col else None,
        }
        results.append(item)

    return results


def get_income_statement(symbol: str, periods: int = 4) -> List[Dict[str, Any]]:
    """
    Lấy kết quả kinh doanh theo quý và tính tăng trưởng YoY.

    Trả về list dict gồm:
    {period, revenue, gross_profit, net_income, revenue_growth_yoy, profit_growth_yoy}.
    Nếu không tìm thấy kỳ cùng năm trước, tăng trưởng YoY sẽ là None.
    """
    symbol = symbol.upper().strip()
    df = _load_finance_table(symbol=symbol, table_type="income", period="quarter", lang="vi")
    if df.empty:
        return []

    period_col = _get_period_column(df)
    revenue_col = _find_metric_column(
        df,
        [
            "revenue",
            "net_revenue",
            "doanh_thu",
            "doanh_thu_thuan",
            "doanh_thu_ban_hang_va_cung_cap_dich_vu",
            "total_revenue",
            "thu_nhap_lai_thuan",
            "thu_nhap_hoat_dong",
            "tong_thu_nhap_hoat_dong",
            "net_interest_income",
            "operating_income",
        ],
    )
    gross_profit_col = _find_metric_column(df, ["gross_profit", "loi_nhuan_gop", "lai_gop", "loi_nhuan_thuan_tu_hoat_dong_kinh_doanh", "operating_profit"])
    net_income_col = _find_metric_column(
        df,
        [
            "net_income",
            "profit_after_tax",
            "loi_nhuan_sau_thue",
            "lnst",
            "loi_nhuan_sau_thue_cua_co_dong_cong_ty_me",
            "net_profit",
            "loi_nhuan_sau_thue_thu_nhap_doanh_nghiep",
            "lnst_cua_cdct_me",
        ],
    )

    # Tạo map kỳ cùng quý năm trước để tính YoY.
    period_keys: List[Tuple[int, int, str]] = []
    for idx, row in df.iterrows():
        value = row.get(period_col) if period_col else idx
        period_keys.append(_period_to_sort_key(value))

    key_to_row: Dict[Tuple[int, int], pd.Series] = {}
    for key, (_, row) in zip(period_keys, df.iterrows()):
        year, quarter, _ = key
        if year and quarter:
            key_to_row[(year, quarter)] = row

    results: List[Dict[str, Any]] = []
    max_rows = min(periods, len(df))

    for position, (_, row) in enumerate(df.head(max_rows).iterrows(), start=1):
        period_value = row.get(period_col) if period_col else None
        sort_key = _period_to_sort_key(period_value)
        year, quarter, _ = sort_key
        prev_row = key_to_row.get((year - 1, quarter)) if year and quarter else None

        revenue = _round_or_none(row.get(revenue_col)) if revenue_col else None
        gross_profit = _round_or_none(row.get(gross_profit_col)) if gross_profit_col else None
        net_income = _round_or_none(row.get(net_income_col)) if net_income_col else None

        prev_revenue = _round_or_none(prev_row.get(revenue_col)) if prev_row is not None and revenue_col else None
        prev_net_income = _round_or_none(prev_row.get(net_income_col)) if prev_row is not None and net_income_col else None

        item = {
            "period": _format_period(period_value, fallback_index=position),
            "revenue": revenue,
            "gross_profit": gross_profit,
            "net_income": net_income,
            "revenue_growth_yoy": _safe_growth(revenue, prev_revenue),
            "profit_growth_yoy": _safe_growth(net_income, prev_net_income),
        }
        results.append(item)

    return results


def get_balance_sheet(symbol: str) -> Dict[str, Any]:
    """
    Lấy bảng cân đối kế toán năm gần nhất.

    Trả về dict gồm {year, total_assets, total_debt, equity, cash}.
    Nếu thiếu dữ liệu, field tương ứng là None.
    """
    symbol = symbol.upper().strip()
    df = _load_finance_table(symbol=symbol, table_type="balance", period="year", lang="vi")
    if df.empty:
        return {"year": None, "total_assets": None, "total_debt": None, "equity": None, "cash": None}

    row = df.iloc[0]
    period_col = _get_period_column(df)

    total_assets_col = _find_metric_column(df, ["total_assets", "tong_tai_san", "tong_cong_tai_san", "tai_san", "assets"])
    total_debt_col = _find_metric_column(
        df,
        [
            "total_debt",
            "total_liabilities",
            "liabilities",
            "tong_no",
            "no_phai_tra",
            "tong_no_phai_tra",
            "tong_cong_no_phai_tra",
        ],
    )
    equity_col = _find_metric_column(
        df,
        [
            "equity",
            "owners_equity",
            "shareholders_equity",
            "von_chu_so_huu",
            "von_csh",
            "tong_von_chu_so_huu",
            "von_va_cac_quy",
        ],
    )
    cash_col = _find_metric_column(
        df,
        [
            "cash",
            "cash_and_equivalents",
            "cash_equivalents",
            "tien_va_tuong_duong_tien",
            "tien_mat",
            "tien",
            "tien_mat_vang_bac_da_quy",
            "tien_gui_tai_nhnn",
        ],
    )

    return {
        "year": _format_period(row.get(period_col)) if period_col else "Không rõ năm",
        "total_assets": _round_or_none(row.get(total_assets_col)) if total_assets_col else None,
        "total_debt": _round_or_none(row.get(total_debt_col)) if total_debt_col else None,
        "equity": _round_or_none(row.get(equity_col)) if equity_col else None,
        "cash": _round_or_none(row.get(cash_col)) if cash_col else None,
    }


def score_fundamentals(
    symbol: str,
    ratios: Optional[List[Dict[str, Any]]] = None,
    income: Optional[List[Dict[str, Any]]] = None,
    balance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Tính điểm sức khoẻ tài chính 0-100 cho một mã cổ phiếu.

    Tiêu chí điểm:
    - ROE, P/E, tăng trưởng doanh thu, tăng trưởng lợi nhuận, Debt/Equity, Net margin.
    Trả về {score, grade, breakdown, summary_vi}.

    Có thể truyền sẵn ratios/income/balance để tránh gọi lại API vnstock.
    """
    symbol = symbol.upper().strip()

    if ratios is None:
        try:
            ratios = get_financial_ratios(symbol)
        except Exception as exc:
            logger.exception("Lỗi get_financial_ratios(%s): %s", symbol, exc)
            ratios = []

    if income is None:
        try:
            income = get_income_statement(symbol, periods=8)
        except Exception as exc:
            logger.exception("Lỗi get_income_statement(%s): %s", symbol, exc)
            income = []

    if balance is None:
        try:
            balance = get_balance_sheet(symbol)
        except Exception as exc:
            logger.exception("Lỗi get_balance_sheet(%s): %s", symbol, exc)
            balance = {}

    latest_ratio = ratios[0] if ratios else {}
    latest_income = income[0] if income else {}

    roe = _safe_float(latest_ratio.get("roe"))
    pe = _safe_float(latest_ratio.get("pe"))
    debt_equity = _safe_float(latest_ratio.get("debt_equity"))
    net_margin = _safe_float(latest_ratio.get("net_margin"))
    revenue_growth = _safe_float(latest_income.get("revenue_growth_yoy"))
    profit_growth = _safe_float(latest_income.get("profit_growth_yoy"))

    # Nếu quý mới nhất chưa có YoY vì thiếu cùng kỳ, tìm quý gần nhất có YoY hợp lệ.
    if revenue_growth is None:
        revenue_growth = _recent_valid(income, "revenue_growth_yoy")
    if profit_growth is None:
        profit_growth = _recent_valid(income, "profit_growth_yoy")

    breakdown: Dict[str, int] = {
        "roe": 0,
        "pe": 0,
        "revenue_growth_yoy": 0,
        "profit_growth_yoy": 0,
        "debt_equity": 0,
        "net_margin": 0,
    }

    if roe is not None:
        if roe > 15:
            breakdown["roe"] = 20
        elif 10 <= roe <= 15:
            breakdown["roe"] = 10

    if pe is not None:
        if pe < 15:
            breakdown["pe"] = 15
        elif 15 <= pe <= 25:
            breakdown["pe"] = 8

    if revenue_growth is not None:
        if revenue_growth > 15:
            breakdown["revenue_growth_yoy"] = 20
        elif 5 <= revenue_growth <= 15:
            breakdown["revenue_growth_yoy"] = 10

    if profit_growth is not None:
        if profit_growth > 20:
            breakdown["profit_growth_yoy"] = 20
        elif 5 <= profit_growth <= 20:
            breakdown["profit_growth_yoy"] = 10

    if debt_equity is not None:
        if debt_equity < 0.5:
            breakdown["debt_equity"] = 15
        elif 0.5 <= debt_equity <= 1.0:
            breakdown["debt_equity"] = 8

    if net_margin is not None and net_margin > 15:
        breakdown["net_margin"] = 10

    score = min(100, sum(breakdown.values()))

    if score >= 80:
        grade = "A"
        label = "rất tốt"
    elif score >= 60:
        grade = "B"
        label = "tốt"
    elif score >= 40:
        grade = "C"
        label = "trung bình"
    else:
        grade = "D"
        label = "yếu hoặc thiếu dữ liệu"

    summary_parts = [f"{symbol} đạt {score}/100 điểm, xếp hạng {grade} - nền tảng cơ bản {label}."]
    if roe is not None:
        summary_parts.append(f"ROE gần nhất khoảng {roe:.2f}%.")
    if pe is not None:
        summary_parts.append(f"P/E gần nhất khoảng {pe:.2f} lần.")
    if revenue_growth is not None:
        summary_parts.append(f"Tăng trưởng doanh thu YoY gần nhất khoảng {revenue_growth:.2f}%.")
    if profit_growth is not None:
        summary_parts.append(f"Tăng trưởng lợi nhuận YoY gần nhất khoảng {profit_growth:.2f}%.")
    if debt_equity is not None:
        summary_parts.append(f"Debt/Equity gần nhất khoảng {debt_equity:.2f} lần.")

    return {
        "score": score,
        "grade": grade,
        "breakdown": breakdown,
        "summary_vi": " ".join(summary_parts),
    }


def get_fundamental_summary(symbol: str) -> Dict[str, Any]:
    """
    Tổng hợp toàn bộ dữ liệu cơ bản thành một dict lớn để truyền vào LLM.

    Trả về {symbol, ratios, income, balance, score, generated_at}.
    Các số tiền lớn được bổ sung bản format string để LLM/dashboard đọc dễ hơn.
    """
    symbol = symbol.upper().strip()

    try:
        ratios = get_financial_ratios(symbol)
    except Exception as exc:
        logger.exception("Lỗi khi lấy ratios cho %s: %s", symbol, exc)
        ratios = []

    try:
        income = get_income_statement(symbol, periods=4)
    except Exception as exc:
        logger.exception("Lỗi khi lấy income statement cho %s: %s", symbol, exc)
        income = []

    try:
        balance = get_balance_sheet(symbol)
    except Exception as exc:
        logger.exception("Lỗi khi lấy balance sheet cho %s: %s", symbol, exc)
        balance = {"year": None, "total_assets": None, "total_debt": None, "equity": None, "cash": None}

    try:
        score = score_fundamentals(symbol, ratios=ratios, income=income, balance=balance)
    except Exception as exc:
        logger.exception("Lỗi khi tính score cho %s: %s", symbol, exc)
        score = {
            "score": 0,
            "grade": "D",
            "breakdown": {},
            "summary_vi": f"Không đủ dữ liệu để chấm điểm cơ bản cho {symbol}.",
        }

    formatted_income: List[Dict[str, Any]] = []
    for item in income:
        formatted = dict(item)
        formatted["revenue_formatted"] = _format_money_value(item.get("revenue"))
        formatted["gross_profit_formatted"] = _format_money_value(item.get("gross_profit"))
        formatted["net_income_formatted"] = _format_money_value(item.get("net_income"))
        formatted_income.append(formatted)

    formatted_balance = dict(balance)
    for key in ["total_assets", "total_debt", "equity", "cash"]:
        formatted_balance[f"{key}_formatted"] = _format_money_value(balance.get(key))

    return {
        "symbol": symbol,
        "ratios": ratios,
        "income": formatted_income,
        "balance": formatted_balance,
        "score": score,
        "generated_at": _now_iso(),
    }


if __name__ == "__main__":
    summary = get_fundamental_summary("VCB")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
