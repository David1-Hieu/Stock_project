"""AI Agent chính điều phối phân tích chứng khoán Việt Nam.

File này kết nối các module:
- analysis.technical: dữ liệu giá và tín hiệu kỹ thuật
- analysis.fundamental: dữ liệu BCTC/chỉ số cơ bản
- agent.ollama_client: LLM local qua Ollama
- agent.prompts: prompt templates
"""

from __future__ import annotations

import json
import logging
import math
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple


# Khi chạy trực tiếp bằng `python agent/agent.py`, Python chỉ thêm thư mục agent/
# vào sys.path. Thêm thư mục gốc project để import được analysis/, technical.py, fundamental.py.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from agent.ollama_client import OllamaConnectionError, get_client
    from agent.prompts import (
        PROMPT_COMPREHENSIVE_REPORT,
        PROMPT_FUNDAMENTAL_ANALYSIS,
        PROMPT_MARKET_OVERVIEW,
        PROMPT_TECHNICAL_ANALYSIS,
        SYSTEM_ANALYST,
    )
except ImportError:  # Hỗ trợ chạy thử khi đang đứng trong thư mục agent/
    from ollama_client import OllamaConnectionError, get_client  # type: ignore
    from prompts import (  # type: ignore
        PROMPT_COMPREHENSIVE_REPORT,
        PROMPT_FUNDAMENTAL_ANALYSIS,
        PROMPT_MARKET_OVERVIEW,
        PROMPT_TECHNICAL_ANALYSIS,
        SYSTEM_ANALYST,
    )

try:
    from analysis.technical import get_technical_summary
except ImportError:  # Hỗ trợ test nhanh khi technical.py nằm cùng thư mục C:\analysis
    try:
        from technical import get_technical_summary  # type: ignore
    except ImportError:
        get_technical_summary = None  # type: ignore

try:
    from analysis.fundamental import get_fundamental_summary
except ImportError:  # Hỗ trợ test nhanh khi fundamental.py nằm cùng thư mục C:\analysis
    try:
        from fundamental import get_fundamental_summary  # type: ignore
    except ImportError:
        get_fundamental_summary = None  # type: ignore


VN_TZ = timezone(timedelta(hours=7))
CACHE_TTL_SECONDS = 600
FULL_REPORT_TIMEOUT_SECONDS = 300
# Với LLM local như llama3.2, full_report nên chỉ gọi Ollama 1 lần để tránh timeout.
FULL_REPORT_SINGLE_LLM_CALL = True

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

# Cache đơn giản trong memory, dùng cho một tiến trình Flask/Python.
_AGENT_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_AGENT_INSTANCE: Optional["StockAnalysisAgent"] = None


def _now_iso() -> str:
    """Trả về thời gian hiện tại theo timezone Việt Nam ở dạng ISO string."""
    return datetime.now(VN_TZ).replace(microsecond=0).isoformat()


def _normalize_symbol(symbol: str) -> str:
    """Chuẩn hoá mã cổ phiếu."""
    return str(symbol or "").strip().upper()


def _safe_float(value: Any) -> Optional[float]:
    """Ép một giá trị về float an toàn, lỗi thì trả None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            value = value.strip().replace(",", "")
            if not value or value.lower() in {"none", "null", "nan", "không có dữ liệu"}:
                return None
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def _format_number(value: Any, key: str = "") -> str:
    """Định dạng số để đưa vào LLM dễ đọc hơn.

    Hàm này không cố đoán quá sâu, chỉ thêm đơn vị phổ biến dựa trên tên key.
    """
    number = _safe_float(value)
    if number is None:
        return "Không có dữ liệu"

    key_norm = key.lower()
    if any(token in key_norm for token in ["percent", "growth", "roe", "roa", "margin", "rsi"]):
        return f"{number:.2f}%"
    if any(token in key_norm for token in ["pe", "pb", "debt_equity"]):
        return f"{number:.2f} lần"
    if "eps" in key_norm:
        return f"{number:,.0f} đ/cp".replace(",", ".")
    if any(token in key_norm for token in ["price", "close", "open", "high", "low", "ema", "bb"]):
        # Giá cổ phiếu Việt Nam từ vnstock thường ở đơn vị nghìn đồng/cp
        # (ví dụ 72.30 nghĩa là khoảng 72.300 đ/cp).
        return f"{number:.2f} nghìn đ/cp"
    if any(token in key_norm for token in ["revenue", "profit", "income", "asset", "debt", "equity", "cash"]):
        abs_number = abs(number)
        sign = "-" if number < 0 else ""
        if abs_number >= 1_000_000_000_000:
            return f"{sign}{abs_number / 1_000_000_000_000:.2f} nghìn tỷ đ"
        if abs_number >= 1_000_000_000:
            return f"{sign}{abs_number / 1_000_000_000:.2f} tỷ đ"
        if abs_number >= 1_000_000:
            return f"{sign}{abs_number / 1_000_000:.2f} triệu đ"
        return f"{number:,.0f} đ".replace(",", ".")

    return f"{number:,.2f}".replace(",", ".")


def _display_key(key: str) -> str:
    """Chuyển key snake_case thành nhãn dễ đọc."""
    labels = {
        "symbol": "Mã cổ phiếu",
        "days": "Số ngày dữ liệu",
        "last_price": "Giá gần nhất",
        "last_date": "Ngày dữ liệu gần nhất",
        "rsi": "RSI",
        "macd": "MACD",
        "macd_signal": "MACD Signal",
        "macd_histogram": "MACD Histogram",
        "bb_upper": "Bollinger Upper",
        "bb_mid": "Bollinger Mid",
        "bb_lower": "Bollinger Lower",
        "ema20": "EMA20",
        "ema50": "EMA50",
        "ema200": "EMA200",
        "trend": "Xu hướng",
        "pe": "P/E",
        "pb": "P/B",
        "roe": "ROE",
        "roa": "ROA",
        "debt_equity": "Nợ/Vốn chủ sở hữu",
        "eps": "EPS",
        "net_margin": "Biên lợi nhuận ròng",
        "revenue": "Doanh thu",
        "gross_profit": "Lợi nhuận gộp",
        "net_income": "Lợi nhuận sau thuế",
        "revenue_growth_yoy": "Tăng trưởng doanh thu YoY",
        "profit_growth_yoy": "Tăng trưởng lợi nhuận YoY",
        "score": "Điểm",
        "grade": "Xếp hạng",
        "breakdown": "Chi tiết điểm",
    }
    return labels.get(key, key.replace("_", " ").title())


def _shorten_text(text: str, max_len: int = 5000) -> str:
    """Rút gọn text quá dài để prompt không phình quá mức."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n... [đã rút gọn để tránh prompt quá dài]"


def format_data_for_llm(data_dict: Any, indent: int = 0) -> str:
    """Chuyển dict/list lồng nhau thành text có cấu trúc dễ đọc cho LLM.

    Args:
        data_dict: Dict/list/scalar cần format.
        indent: Số cấp thụt dòng nội bộ.

    Returns:
        Chuỗi text nhiều dòng, dễ đưa vào prompt.
    """
    prefix = "  " * indent

    if data_dict is None:
        return prefix + "Không có dữ liệu"

    if isinstance(data_dict, dict):
        lines: List[str] = []
        for key, value in data_dict.items():
            label = _display_key(str(key))
            if isinstance(value, dict):
                lines.append(f"{prefix}{label}:")
                lines.append(format_data_for_llm(value, indent + 1))
            elif isinstance(value, list):
                lines.append(f"{prefix}{label}:")
                if not value:
                    lines.append(f"{prefix}  Không có dữ liệu")
                else:
                    for idx, item in enumerate(value[:8], start=1):
                        lines.append(f"{prefix}  [{idx}]")
                        lines.append(format_data_for_llm(item, indent + 2))
                    if len(value) > 8:
                        lines.append(f"{prefix}  ... còn {len(value) - 8} dòng")
            elif isinstance(value, bool):
                lines.append(f"{prefix}{label}: {'Có' if value else 'Không'}")
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                lines.append(f"{prefix}{label}: {_format_number(value, str(key))}")
            else:
                lines.append(f"{prefix}{label}: {value if value not in [None, ''] else 'Không có dữ liệu'}")
        return "\n".join(lines)

    if isinstance(data_dict, list):
        if not data_dict:
            return prefix + "Không có dữ liệu"
        lines = []
        for idx, item in enumerate(data_dict[:8], start=1):
            lines.append(f"{prefix}[{idx}]")
            lines.append(format_data_for_llm(item, indent + 1))
        if len(data_dict) > 8:
            lines.append(f"{prefix}... còn {len(data_dict) - 8} dòng")
        return "\n".join(lines)

    if isinstance(data_dict, (int, float)) and not isinstance(data_dict, bool):
        return prefix + _format_number(data_dict)

    return prefix + str(data_dict)


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    """Lấy dữ liệu cache nếu còn hạn 10 phút."""
    item = _AGENT_CACHE.get(key)
    if not item:
        return None
    created_at, value = item
    if time.time() - created_at > CACHE_TTL_SECONDS:
        _AGENT_CACHE.pop(key, None)
        return None
    return deepcopy(value)


def _cache_set(key: str, value: Dict[str, Any]) -> None:
    """Lưu dữ liệu vào cache memory."""
    _AGENT_CACHE[key] = (time.time(), deepcopy(value))


def _extract_score_info(fundamental_result: Dict[str, Any]) -> Dict[str, Any]:
    """Trích score/grade từ kết quả fundamental."""
    data = fundamental_result.get("fundamental_data") or fundamental_result.get("fundamental") or {}
    score_obj = data.get("score", {}) if isinstance(data, dict) else {}

    if isinstance(score_obj, dict):
        return {
            "score": score_obj.get("score"),
            "grade": score_obj.get("grade"),
            "breakdown": score_obj.get("breakdown", {}),
            "summary_vi": score_obj.get("summary_vi"),
        }
    return {"score": None, "grade": None, "breakdown": {}, "summary_vi": None}


def _error(message: str, symbol: Optional[str] = None) -> Dict[str, Any]:
    """Tạo response lỗi thống nhất."""
    result: Dict[str, Any] = {"error": message, "generated_at": _now_iso()}
    if symbol:
        result["symbol"] = symbol
    return result


class StockAnalysisAgent:
    """Agent chính điều phối phân tích kỹ thuật, cơ bản và LLM local."""

    def __init__(self) -> None:
        """Khởi tạo agent, logger và OllamaClient.

        Nếu Ollama chưa chạy, agent vẫn được tạo nhưng các method LLM sẽ trả về error rõ ràng.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.ollama_error: Optional[str] = None
        self.client = None
        try:
            self.client = get_client()
            self.logger.info("OllamaClient đã sẵn sàng")
        except OllamaConnectionError as exc:
            self.ollama_error = str(exc)
            self.logger.warning("Không thể khởi tạo OllamaClient: %s", exc)
        except Exception as exc:  # noqa: BLE001 - cần không làm crash Flask app
            self.ollama_error = "Ollama chưa được khởi động. Chạy: ollama serve"
            self.logger.exception("Lỗi không xác định khi khởi tạo OllamaClient: %s", exc)

    def _ensure_ollama(self) -> Optional[Dict[str, Any]]:
        """Kiểm tra Ollama đã sẵn sàng chưa."""
        if self.client is None:
            return _error("Ollama chưa được khởi động. Chạy: ollama serve")
        return None


    def _get_raw_technical_data(self, symbol: str) -> Dict[str, Any]:
        """Lấy dữ liệu kỹ thuật thuần, không gọi LLM.

        Dùng trong full_report để giảm số lần gọi Ollama. Kết quả được cache 10 phút.
        """
        symbol = _normalize_symbol(symbol)
        cached = _cache_get(f"raw_technical:{symbol}")
        if cached:
            return cached
        if get_technical_summary is None:
            return _error("Không import được analysis.technical.get_technical_summary", symbol)
        start = time.perf_counter()
        try:
            data = get_technical_summary(symbol)
            _cache_set(f"raw_technical:{symbol}", data)
            self.logger.info("Lấy raw technical %s trong %.2fs", symbol, time.perf_counter() - start)
            return data
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Lỗi khi lấy raw technical %s", symbol)
            return _error(f"Lỗi lấy dữ liệu kỹ thuật {symbol}: {exc}", symbol)

    def _get_raw_fundamental_data(self, symbol: str) -> Dict[str, Any]:
        """Lấy dữ liệu cơ bản thuần, không gọi LLM.

        Dùng trong full_report để giảm số lần gọi Ollama. Kết quả được cache 10 phút.
        """
        symbol = _normalize_symbol(symbol)
        cached = _cache_get(f"raw_fundamental:{symbol}")
        if cached:
            return cached
        if get_fundamental_summary is None:
            return _error("Không import được analysis.fundamental.get_fundamental_summary", symbol)
        start = time.perf_counter()
        try:
            data = get_fundamental_summary(symbol)
            _cache_set(f"raw_fundamental:{symbol}", data)
            self.logger.info("Lấy raw fundamental %s trong %.2fs", symbol, time.perf_counter() - start)
            return data
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Lỗi khi lấy raw fundamental %s", symbol)
            return _error(f"Lỗi lấy dữ liệu cơ bản {symbol}: {exc}", symbol)

    def analyze_technical(self, symbol: str) -> Dict[str, Any]:
        """Phân tích kỹ thuật một mã cổ phiếu bằng dữ liệu indicator và LLM.

        Args:
            symbol: Mã cổ phiếu Việt Nam, ví dụ VNM, FPT, VCB.

        Returns:
            Dict gồm dữ liệu kỹ thuật, phân tích LLM và thời gian tạo.
        """
        symbol = _normalize_symbol(symbol)
        if not symbol:
            return _error("Mã cổ phiếu không hợp lệ")
        if get_technical_summary is None:
            return _error("Không import được analysis.technical.get_technical_summary", symbol)

        cached = _cache_get(f"technical:{symbol}")
        if cached:
            return cached

        ollama_error = self._ensure_ollama()
        if ollama_error:
            ollama_error["symbol"] = symbol
            return ollama_error

        start = time.perf_counter()
        try:
            self.logger.info("Bắt đầu phân tích kỹ thuật %s", symbol)
            technical_data = get_technical_summary(symbol)
            technical_text = format_data_for_llm(technical_data)
            user_prompt = PROMPT_TECHNICAL_ANALYSIS.format(
                symbol=symbol,
                technical_data=_shorten_text(technical_text, max_len=7000),
            )
            llm_analysis = self.client.analyze(  # type: ignore[union-attr]
                SYSTEM_ANALYST,
                user_prompt,
                temperature=0.2,
            )
            result = {
                "symbol": symbol,
                "technical_data": technical_data,
                "llm_analysis": llm_analysis,
                "generated_at": _now_iso(),
            }
            _cache_set(f"technical:{symbol}", result)
            self.logger.info("Hoàn tất phân tích kỹ thuật %s trong %.2fs", symbol, time.perf_counter() - start)
            return result
        except Exception as exc:  # noqa: BLE001 - trả lỗi JSON cho dashboard
            self.logger.exception("Lỗi khi phân tích kỹ thuật %s", symbol)
            return _error(f"Lỗi phân tích kỹ thuật {symbol}: {exc}", symbol)

    def analyze_fundamental(self, symbol: str) -> Dict[str, Any]:
        """Phân tích cơ bản một mã cổ phiếu bằng dữ liệu BCTC và LLM.

        Args:
            symbol: Mã cổ phiếu Việt Nam.

        Returns:
            Dict gồm dữ liệu cơ bản, score và phân tích LLM.
        """
        symbol = _normalize_symbol(symbol)
        if not symbol:
            return _error("Mã cổ phiếu không hợp lệ")
        if get_fundamental_summary is None:
            return _error("Không import được analysis.fundamental.get_fundamental_summary", symbol)

        cached = _cache_get(f"fundamental:{symbol}")
        if cached:
            return cached

        ollama_error = self._ensure_ollama()
        if ollama_error:
            ollama_error["symbol"] = symbol
            return ollama_error

        start = time.perf_counter()
        try:
            self.logger.info("Bắt đầu phân tích cơ bản %s", symbol)
            fundamental_data = get_fundamental_summary(symbol)
            fundamental_text = format_data_for_llm(fundamental_data)
            user_prompt = PROMPT_FUNDAMENTAL_ANALYSIS.format(
                symbol=symbol,
                fundamental_data=_shorten_text(fundamental_text, max_len=9000),
            )
            llm_analysis = self.client.analyze(  # type: ignore[union-attr]
                SYSTEM_ANALYST,
                user_prompt,
                temperature=0.2,
            )
            score_info = fundamental_data.get("score", {}) if isinstance(fundamental_data, dict) else {}
            result = {
                "symbol": symbol,
                "fundamental_data": fundamental_data,
                "llm_analysis": llm_analysis,
                "score": score_info.get("score") if isinstance(score_info, dict) else None,
                "grade": score_info.get("grade") if isinstance(score_info, dict) else None,
                "generated_at": _now_iso(),
            }
            _cache_set(f"fundamental:{symbol}", result)
            self.logger.info("Hoàn tất phân tích cơ bản %s trong %.2fs", symbol, time.perf_counter() - start)
            return result
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Lỗi khi phân tích cơ bản %s", symbol)
            return _error(f"Lỗi phân tích cơ bản {symbol}: {exc}", symbol)

    def _compact_technical_for_llm(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Rút gọn dữ liệu kỹ thuật để LLM không hiểu nhầm tín hiệu inactive.

        Output JSON gốc vẫn giữ đủ signals. Hàm này chỉ dùng để tạo prompt.
        """
        if not isinstance(data, dict):
            return {"error": "Không có dữ liệu kỹ thuật hợp lệ"}

        signals = data.get("signals", {}) if isinstance(data.get("signals"), dict) else {}
        active_signals: Dict[str, Any] = {}
        inactive_signal_names: List[str] = []
        for name, signal in signals.items():
            if isinstance(signal, dict) and signal.get("active") is True:
                active_signals[name] = {
                    "value": signal.get("value"),
                    "description": signal.get("description"),
                }
            else:
                inactive_signal_names.append(str(name))

        return {
            "symbol": data.get("symbol"),
            "last_price": data.get("last_price"),
            "last_date": data.get("last_date"),
            "trend": data.get("trend"),
            "indicators": data.get("indicators", {}),
            "active_signals_only": active_signals or "Không có tín hiệu active",
            "inactive_signals_ignore": inactive_signal_names,
            "signal_rule": "Chỉ phân tích active_signals_only. Không diễn giải mô tả của inactive_signals_ignore như tín hiệu đang xảy ra.",
            "price_unit_note": "Các mức giá như 72.30 là nghìn đồng/cổ phiếu, không phải 72.30 đồng.",
        }

    def _compact_fundamental_for_llm(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Rút gọn dữ liệu cơ bản để prompt ngắn và rõ hơn."""
        if not isinstance(data, dict):
            return {"error": "Không có dữ liệu cơ bản hợp lệ"}

        ratios = data.get("ratios") if isinstance(data.get("ratios"), list) else []
        income = data.get("income") if isinstance(data.get("income"), list) else []
        balance = data.get("balance") if isinstance(data.get("balance"), dict) else {}
        score = data.get("score") if isinstance(data.get("score"), dict) else {}

        return {
            "symbol": data.get("symbol"),
            "latest_ratios": ratios[0] if ratios else {},
            "ratio_history": ratios[:4],
            "recent_income": income[:4],
            "latest_balance": balance,
            "score": score,
            "data_limit_note": "Nếu YoY growth bị null, nguyên nhân thường là bản community chỉ có 4 kỳ nên thiếu cùng kỳ năm trước.",
        }


    def _build_rule_based_report(
        self,
        symbol: str,
        technical_data: Dict[str, Any],
        fundamental_data: Dict[str, Any],
        score_obj: Dict[str, Any],
        note: str = "",
    ) -> str:
        """Tạo báo cáo fallback không cần LLM khi Ollama quá chậm hoặc timeout."""
        indicators = technical_data.get("indicators", {}) if isinstance(technical_data, dict) else {}
        signals = technical_data.get("signals", {}) if isinstance(technical_data, dict) else {}
        active_signals = []
        if isinstance(signals, dict):
            for name, payload in signals.items():
                if isinstance(payload, dict) and payload.get("active") is True:
                    active_signals.append(name)

        last_price = technical_data.get("last_price") if isinstance(technical_data, dict) else None
        trend = technical_data.get("trend") if isinstance(technical_data, dict) else None
        rsi = indicators.get("rsi") if isinstance(indicators, dict) else None
        ema20 = indicators.get("ema20") if isinstance(indicators, dict) else None
        ema50 = indicators.get("ema50") if isinstance(indicators, dict) else None
        ema200 = indicators.get("ema200") if isinstance(indicators, dict) else None
        bb_upper = indicators.get("bb_upper") if isinstance(indicators, dict) else None
        bb_lower = indicators.get("bb_lower") if isinstance(indicators, dict) else None
        macd = indicators.get("macd") if isinstance(indicators, dict) else None
        macd_signal = indicators.get("macd_signal") if isinstance(indicators, dict) else None

        ratios = fundamental_data.get("ratios", []) if isinstance(fundamental_data, dict) else []
        latest_ratio = ratios[0] if isinstance(ratios, list) and ratios else {}
        balance = fundamental_data.get("balance", {}) if isinstance(fundamental_data, dict) else {}
        income = fundamental_data.get("income", []) if isinstance(fundamental_data, dict) else []
        latest_income = income[0] if isinstance(income, list) and income else {}

        score = score_obj.get("score") if isinstance(score_obj, dict) else None
        grade = score_obj.get("grade") if isinstance(score_obj, dict) else None
        pe = latest_ratio.get("pe") if isinstance(latest_ratio, dict) else None
        pb = latest_ratio.get("pb") if isinstance(latest_ratio, dict) else None
        roe = latest_ratio.get("roe") if isinstance(latest_ratio, dict) else None
        roa = latest_ratio.get("roa") if isinstance(latest_ratio, dict) else None
        de = latest_ratio.get("debt_equity") if isinstance(latest_ratio, dict) else None
        margin = latest_ratio.get("net_margin") if isinstance(latest_ratio, dict) else None

        # Rule khuyến nghị tham khảo, không cá nhân hoá.
        recommendation = "Theo dõi thêm"
        score_num = _safe_float(score)
        rsi_num = _safe_float(rsi)
        pe_num = _safe_float(pe)
        if trend == "TĂNG" and score_num is not None and score_num >= 60 and (rsi_num is None or rsi_num < 70):
            recommendation = "Mua"
        elif trend == "GIẢM" or (score_num is not None and score_num < 40) or (pe_num is not None and pe_num > 30):
            recommendation = "Thận trọng"

        active_text = ", ".join(active_signals) if active_signals else "Không có tín hiệu active nổi bật"
        support_resistance = "Không đủ dữ liệu"
        if bb_lower is not None and bb_upper is not None:
            support_resistance = f"hỗ trợ quanh {_format_number(bb_lower, 'price')}, kháng cự quanh {_format_number(bb_upper, 'price')}"

        note_text = f"\n\n_Ghi chú hệ thống: Ollama không phản hồi kịp nên báo cáo này được tạo bằng rule-based fallback. Chi tiết: {note}_" if note else ""

        return f"""## Tóm tắt điều hành
{symbol} có giá gần nhất {_format_number(last_price, 'price')}, xu hướng kỹ thuật tổng quát: {trend or 'Không có dữ liệu'}. RSI hiện ở mức {_format_number(rsi, 'rsi')}, nên cần đọc cùng EMA và Bollinger Bands thay vì kết luận riêng lẻ. Điểm cơ bản hiện là {score if score is not None else 'Không có dữ liệu'}/100, xếp hạng {grade or 'Không có dữ liệu'}.

## Phân tích kỹ thuật
- Giá gần nhất: {_format_number(last_price, 'price')}.
- RSI: {_format_number(rsi, 'rsi')}.
- MACD / Signal: {_format_number(macd, 'macd')} / {_format_number(macd_signal, 'macd_signal')}.
- EMA20 / EMA50 / EMA200: {_format_number(ema20, 'price')} / {_format_number(ema50, 'price')} / {_format_number(ema200, 'price')}.
- Tín hiệu đang active: {active_text}.
- Vùng tham khảo: {support_resistance}.

## Phân tích cơ bản
- P/E: {_format_number(pe, 'pe')}; P/B: {_format_number(pb, 'pb')}.
- ROE: {_format_number(roe, 'roe')}; ROA: {_format_number(roa, 'roa')}.
- Debt/Equity: {_format_number(de, 'debt_equity')}; Net margin: {_format_number(margin, 'net_margin')}.
- Doanh thu kỳ gần nhất: {_format_number(latest_income.get('revenue') if isinstance(latest_income, dict) else None, 'revenue')}.
- Lợi nhuận sau thuế kỳ gần nhất: {_format_number(latest_income.get('net_income') if isinstance(latest_income, dict) else None, 'net_income')}.
- Tổng tài sản: {_format_number(balance.get('total_assets') if isinstance(balance, dict) else None, 'asset')}; vốn chủ sở hữu: {_format_number(balance.get('equity') if isinstance(balance, dict) else None, 'equity')}.

## Điểm mạnh
- Dữ liệu kỹ thuật, định giá, khả năng sinh lời và bảng cân đối đã được lấy thành công.
- Nếu ROE/ROA cao và biên lợi nhuận tốt, đây là điểm tích cực cần tiếp tục theo dõi.

## Rủi ro cần lưu ý
- Dữ liệu YoY growth có thể thiếu do bản community của vnstock chỉ trả số kỳ giới hạn.
- Tín hiệu kỹ thuật có thể thay đổi nhanh theo giá và thanh khoản.
- Báo cáo fallback không thay thế phân tích LLM đầy đủ.

## Khuyến nghị
- Mức khuyến nghị: {recommendation}
- Luận điểm chính: Kết hợp xu hướng kỹ thuật {trend or 'không rõ'}, score {score if score is not None else 'không có dữ liệu'}/100 và các chỉ số định giá/sinh lời hiện có.
- Vùng giá tham khảo: {support_resistance}.

## Tuyên bố miễn trừ trách nhiệm
Báo cáo này chỉ phục vụ mục đích nghiên cứu cá nhân, không phải khuyến nghị đầu tư hay lời mời mua/bán chứng khoán. Nhà đầu tư cần tự chịu trách nhiệm với quyết định của mình.{note_text}""".strip()

    def _call_comprehensive_llm(self, user_prompt: str) -> str:
        """Gọi Ollama với cấu hình nhẹ hơn cho full_report."""
        messages = [
            {"role": "system", "content": SYSTEM_ANALYST},
            {"role": "user", "content": user_prompt},
        ]
        try:
            return self.client.chat(  # type: ignore[union-attr]
                messages=messages,
                temperature=0.2,
                max_tokens=750,
                timeout=240,
                max_attempts=1,
            )
        except TypeError:
            # Tương thích nếu người dùng chưa thay ollama_client.py bản mới.
            return self.client.analyze(  # type: ignore[union-attr]
                SYSTEM_ANALYST,
                user_prompt,
                temperature=0.2,
            )

    def full_report(self, symbol: str) -> Dict[str, Any]:
        """Tạo báo cáo đầy đủ cho một mã cổ phiếu.

        Bản tối ưu cho máy local: chạy song song phần lấy dữ liệu kỹ thuật/cơ bản,
        sau đó chỉ gọi Ollama 1 lần để tạo báo cáo tổng hợp. Cách này tránh việc
        `full_report()` phải gọi 3 lần LLM, vốn rất dễ timeout với llama3.2 chạy local.
        """
        symbol = _normalize_symbol(symbol)
        if not symbol:
            return _error("Mã cổ phiếu không hợp lệ")

        cached = _cache_get(f"full:{symbol}")
        if cached:
            return cached

        ollama_error = self._ensure_ollama()
        if ollama_error:
            ollama_error["symbol"] = symbol
            return ollama_error

        start = time.perf_counter()
        try:
            self.logger.info("Bắt đầu full_report tối ưu %s", symbol)
            results: Dict[str, Dict[str, Any]] = {}

            # Chỉ lấy raw data song song, không gọi LLM trong 2 worker.
            with ThreadPoolExecutor(max_workers=2) as executor:
                future_map = {
                    executor.submit(self._get_raw_technical_data, symbol): "technical_data",
                    executor.submit(self._get_raw_fundamental_data, symbol): "fundamental_data",
                }
                for future in as_completed(future_map, timeout=FULL_REPORT_TIMEOUT_SECONDS):
                    name = future_map[future]
                    try:
                        results[name] = future.result(timeout=5)
                    except Exception as exc:  # noqa: BLE001
                        self.logger.exception("Lỗi worker %s trong full_report %s", name, symbol)
                        results[name] = _error(str(exc), symbol)

            technical_data = results.get("technical_data", {})
            fundamental_data = results.get("fundamental_data", {})

            if technical_data.get("error") and fundamental_data.get("error"):
                return _error(
                    f"Không tạo được báo cáo vì cả technical và fundamental đều lỗi: "
                    f"{technical_data.get('error')} | {fundamental_data.get('error')}",
                    symbol,
                )

            technical_for_llm = self._compact_technical_for_llm(technical_data)
            fundamental_for_llm = self._compact_fundamental_for_llm(fundamental_data)
            technical_text = format_data_for_llm(technical_for_llm)
            fundamental_text = format_data_for_llm(fundamental_for_llm)
            score_obj = fundamental_data.get("score", {}) if isinstance(fundamental_data, dict) else {}
            score_text = format_data_for_llm(score_obj)

            user_prompt = PROMPT_COMPREHENSIVE_REPORT.format(
                symbol=symbol,
                technical_data=_shorten_text(technical_text, max_len=1800),
                fundamental_data=_shorten_text(fundamental_text, max_len=2200),
                score=_shorten_text(score_text, max_len=600),
            )
            llm_fallback_used = False
            try:
                comprehensive_analysis = self._call_comprehensive_llm(user_prompt)
            except OllamaConnectionError as exc:
                self.logger.warning("Ollama không phản hồi kịp, dùng rule-based fallback cho %s: %s", symbol, exc)
                comprehensive_analysis = self._build_rule_based_report(
                    symbol=symbol,
                    technical_data=technical_data,
                    fundamental_data=fundamental_data,
                    score_obj=score_obj if isinstance(score_obj, dict) else {},
                    note=str(exc),
                )
                llm_fallback_used = True

            score_info = score_obj if isinstance(score_obj, dict) else {}
            result = {
                "symbol": symbol,
                "technical": {
                    "symbol": symbol,
                    "technical_data": technical_data,
                    "llm_analysis": "Đã được tổng hợp trong comprehensive_analysis để giảm thời gian xử lý.",
                    "generated_at": _now_iso(),
                },
                "fundamental": {
                    "symbol": symbol,
                    "fundamental_data": fundamental_data,
                    "llm_analysis": "Đã được tổng hợp trong comprehensive_analysis để giảm thời gian xử lý.",
                    "score": score_info.get("score"),
                    "grade": score_info.get("grade"),
                    "generated_at": _now_iso(),
                },
                "comprehensive_analysis": comprehensive_analysis,
                "llm_fallback_used": llm_fallback_used,
                "score": score_info.get("score"),
                "grade": score_info.get("grade"),
                "generated_at": _now_iso(),
            }
            _cache_set(f"full:{symbol}", result)
            self.logger.info("Hoàn tất full_report tối ưu %s trong %.2fs", symbol, time.perf_counter() - start)
            return result
        except TimeoutError:
            self.logger.exception("Timeout khi lấy dữ liệu cho full_report %s", symbol)
            partial: Dict[str, Any] = {
                "symbol": symbol,
                "error": "Timeout khi lấy dữ liệu cho báo cáo đầy đủ. Hãy thử lại hoặc gọi riêng analyze_technical/analyze_fundamental.",
                "generated_at": _now_iso(),
            }
            return partial
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Lỗi khi tạo full_report %s", symbol)
            return _error(f"Lỗi tạo báo cáo đầy đủ {symbol}: {exc}", symbol)

    def portfolio_overview(self, holdings_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Phân tích tổng quan danh mục đầu tư.

        Args:
            holdings_list: List dict dạng {symbol, quantity, avg_cost, current_price, pl_percent}.

        Returns:
            Dict gồm holdings kèm RSI/trend và nhận định LLM.
        """
        if not isinstance(holdings_list, list):
            return _error("holdings_list phải là list")

        ollama_error = self._ensure_ollama()
        if ollama_error:
            return ollama_error

        start = time.perf_counter()
        enriched: List[Dict[str, Any]] = []
        for holding in holdings_list:
            item = dict(holding or {})
            symbol = _normalize_symbol(item.get("symbol", ""))
            item["symbol"] = symbol
            if symbol and get_technical_summary is not None:
                try:
                    summary = get_technical_summary(symbol, days=260)
                    indicators = summary.get("indicators", {}) if isinstance(summary, dict) else {}
                    item["rsi"] = indicators.get("rsi") if isinstance(indicators, dict) else None
                    item["trend"] = summary.get("trend") if isinstance(summary, dict) else None
                    item["last_price_from_market"] = summary.get("last_price") if isinstance(summary, dict) else None
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning("Không lấy được technical nhanh cho %s: %s", symbol, exc)
                    item["technical_error"] = str(exc)
            enriched.append(item)

        try:
            portfolio_text = format_data_for_llm({"holdings": enriched})
            user_prompt = PROMPT_MARKET_OVERVIEW.format(
                portfolio_data=_shorten_text(portfolio_text, max_len=9000)
            )
            llm_overview = self.client.analyze(  # type: ignore[union-attr]
                SYSTEM_ANALYST,
                user_prompt,
                temperature=0.25,
            )
            result = {
                "holdings_with_signals": enriched,
                "llm_overview": llm_overview,
                "generated_at": _now_iso(),
            }
            self.logger.info("Hoàn tất portfolio_overview trong %.2fs", time.perf_counter() - start)
            return result
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Lỗi khi phân tích portfolio_overview")
            return _error(f"Lỗi phân tích danh mục: {exc}")


def get_agent() -> StockAnalysisAgent:
    """Trả về singleton StockAnalysisAgent."""
    global _AGENT_INSTANCE
    if _AGENT_INSTANCE is None:
        _AGENT_INSTANCE = StockAnalysisAgent()
    return _AGENT_INSTANCE


if __name__ == "__main__":
    # Test nhanh: python agent/agent.py FPT
    import sys

    test_symbol = _normalize_symbol(sys.argv[1] if len(sys.argv) > 1 else "FPT")
    agent = get_agent()
    output = agent.full_report(test_symbol)
    print(json.dumps(output, ensure_ascii=False, indent=2))
