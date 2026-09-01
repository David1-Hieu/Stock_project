"""Tạo báo cáo HTML/PDF cho AI Agent phân tích chứng khoán Việt Nam.

Module này nhận dữ liệu từ StockAnalysisAgent.full_report(symbol), render HTML bằng
Jinja2 và có thể xuất PDF bằng WeasyPrint nếu môi trường đã cài đầy đủ thư viện hệ thống.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError as exc:  # pragma: no cover
    raise ImportError("Thiếu thư viện jinja2. Cài bằng: pip install jinja2") from exc

try:
    import markdown as markdown_lib
except ImportError:  # pragma: no cover
    markdown_lib = None

LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parent
TEMPLATE_DIR = MODULE_DIR / "templates"
REPORTS_DIR = PROJECT_ROOT / "reports"

SUPPORTED_FORMATS = {"html", "pdf"}


# ---------------------------------------------------------------------------
# Helper format dữ liệu
# ---------------------------------------------------------------------------

def safe_get(data: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Lấy giá trị lồng nhau từ dict theo đường dẫn a.b.c, nếu thiếu trả default."""
    current: Any = data
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def fmt_number(value: Any, digits: int = 2, suffix: str = "") -> str:
    """Format số gọn gàng; nếu thiếu dữ liệu trả 'Không có dữ liệu'."""
    if value is None or value == "":
        return "Không có dữ liệu"
    try:
        number = float(value)
        text = f"{number:,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return f"{text}{suffix}"
    except (TypeError, ValueError):
        return str(value)


def fmt_vnd(value: Any) -> str:
    """Format số tiền VND dạng 1.234.567 đ; nếu thiếu dữ liệu trả thông báo rõ ràng."""
    if value is None or value == "":
        return "Không có dữ liệu"
    try:
        number = int(round(float(value)))
        return f"{number:,}".replace(",", ".") + " đ"
    except (TypeError, ValueError):
        return str(value)


def markdown_to_html(text: Any) -> str:
    """Chuyển Markdown sang HTML. Nếu thiếu thư viện markdown, dùng fallback đơn giản."""
    if not text:
        return "<p>Không có dữ liệu</p>"

    text = str(text).strip()
    if markdown_lib is None:
        # Fallback rất nhẹ: giữ xuống dòng và escape cơ bản để không crash.
        escaped = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )
        return f"<p>{escaped}</p>"

    return markdown_lib.markdown(
        text,
        extensions=["extra", "sane_lists", "tables"],
        output_format="html5",
    )


def slugify_symbol(symbol: Any) -> str:
    """Làm sạch mã chứng khoán để dùng trong tên file."""
    raw = str(symbol or "REPORT").upper().strip()
    return re.sub(r"[^A-Z0-9_-]", "", raw) or "REPORT"


def now_stamp() -> str:
    """Trả timestamp cho tên file báo cáo."""
    return datetime.now().strftime("%Y%m%d_%H%M")


def detect_sentiment(report_data: Dict[str, Any]) -> Dict[str, str]:
    """Suy luận sentiment để tô màu khuyến nghị trong template."""
    analysis = str(report_data.get("comprehensive_analysis", "")).upper()
    trend = str(safe_get(report_data, "technical.technical_data.trend", "")).upper()
    score = safe_get(report_data, "score", safe_get(report_data, "fundamental.score", 0)) or 0

    try:
        score_num = int(float(score))
    except (TypeError, ValueError):
        score_num = 0

    if "TIÊU CỰC" in analysis or (trend == "GIẢM" and score_num < 45):
        return {"label": "THẬN TRỌNG", "class": "caution"}
    if "TÍCH CỰC" in analysis or score_num >= 70:
        return {"label": "TÍCH CỰC", "class": "positive"}
    if "MUA" in analysis and score_num >= 55:
        return {"label": "TÍCH CỰC", "class": "positive"}
    return {"label": "TRUNG LẬP", "class": "neutral"}


def metric_status(metric: str, value: Any) -> Dict[str, str]:
    """Trả trạng thái/icon/màu cho chỉ số kỹ thuật hoặc cơ bản."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return {"icon": "⚪", "text": "Không có dữ liệu", "class": "neutral"}

    metric = metric.lower()
    if metric == "rsi":
        if number < 30:
            return {"icon": "🟢", "text": "Quá bán", "class": "positive"}
        if number > 70:
            return {"icon": "🔴", "text": "Quá mua", "class": "negative"}
        return {"icon": "🟡", "text": "Trung tính", "class": "neutral"}

    if metric in {"macd_hist", "macd"}:
        if number > 0:
            return {"icon": "🟢", "text": "Động lượng cải thiện", "class": "positive"}
        if number < 0:
            return {"icon": "🔴", "text": "Động lượng yếu", "class": "negative"}
        return {"icon": "🟡", "text": "Trung tính", "class": "neutral"}

    if metric in {"pe", "pb", "debt_equity"}:
        return {"icon": "🟡", "text": "Cần so sánh ngành", "class": "neutral"}

    if metric in {"roe", "roa", "net_margin"}:
        if number >= 15:
            return {"icon": "🟢", "text": "Tốt", "class": "positive"}
        if number >= 8:
            return {"icon": "🟡", "text": "Trung bình", "class": "neutral"}
        return {"icon": "🔴", "text": "Thấp", "class": "negative"}

    return {"icon": "🟡", "text": "Theo dõi", "class": "neutral"}


def active_signals(signals: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Lọc danh sách tín hiệu kỹ thuật đang active."""
    if not isinstance(signals, dict):
        return []
    result = []
    for key, item in signals.items():
        if isinstance(item, dict) and item.get("active"):
            result.append(
                {
                    "key": key,
                    "name": key.replace("_", " ").title(),
                    "value": item.get("value"),
                    "description": item.get("description", ""),
                    "class": "negative" if any(x in key for x in ["bearish", "death", "overbought", "below"]) else "positive",
                }
            )
    return result


def build_view_model(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """Chuẩn bị dữ liệu thân thiện cho template Jinja2."""
    symbol = report_data.get("symbol", "N/A")
    technical = safe_get(report_data, "technical.technical_data", {}) or {}
    fundamental = safe_get(report_data, "fundamental.fundamental_data", {}) or {}
    indicators = technical.get("indicators", {}) if isinstance(technical, dict) else {}
    ratios = fundamental.get("ratios", []) if isinstance(fundamental, dict) else []
    income = fundamental.get("income", []) if isinstance(fundamental, dict) else []
    balance = fundamental.get("balance", {}) if isinstance(fundamental, dict) else {}
    score_data = fundamental.get("score", {}) if isinstance(fundamental, dict) else {}

    latest_ratio = ratios[0] if ratios else {}
    sentiment = detect_sentiment(report_data)
    signals = active_signals(technical.get("signals", {}))
    score = report_data.get("score", safe_get(report_data, "fundamental.score", score_data.get("score", 0))) or 0
    grade = report_data.get("grade", safe_get(report_data, "fundamental.grade", score_data.get("grade", "N/A"))) or "N/A"

    score_num = 0
    try:
        score_num = max(0, min(100, int(float(score))))
    except (TypeError, ValueError):
        pass

    technical_rows = [
        {"name": "RSI(14)", "value": fmt_number(indicators.get("rsi")), "status": metric_status("rsi", indicators.get("rsi"))},
        {"name": "MACD", "value": fmt_number(indicators.get("macd")), "status": metric_status("macd", indicators.get("macd"))},
        {"name": "MACD Signal", "value": fmt_number(indicators.get("macd_signal")), "status": metric_status("macd", indicators.get("macd_signal"))},
        {"name": "MACD Hist", "value": fmt_number(indicators.get("macd_hist")), "status": metric_status("macd_hist", indicators.get("macd_hist"))},
        {"name": "EMA20", "value": fmt_number(indicators.get("ema20"), suffix=" nghìn đ"), "status": {"icon": "🟡", "text": "Theo dõi", "class": "neutral"}},
        {"name": "EMA50", "value": fmt_number(indicators.get("ema50"), suffix=" nghìn đ"), "status": {"icon": "🟡", "text": "Theo dõi", "class": "neutral"}},
        {"name": "BB Upper", "value": fmt_number(indicators.get("bb_upper"), suffix=" nghìn đ"), "status": {"icon": "🟡", "text": "Kháng cự gần", "class": "neutral"}},
        {"name": "BB Lower", "value": fmt_number(indicators.get("bb_lower"), suffix=" nghìn đ"), "status": {"icon": "🟡", "text": "Hỗ trợ gần", "class": "neutral"}},
    ]

    ratio_rows = []
    for row in ratios:
        ratio_rows.append(
            {
                "year": row.get("year", "Không rõ"),
                "pe": fmt_number(row.get("pe")),
                "pb": fmt_number(row.get("pb")),
                "roe": fmt_number(row.get("roe"), suffix="%"),
                "roa": fmt_number(row.get("roa"), suffix="%"),
                "eps": fmt_number(row.get("eps"), digits=0, suffix=" đ"),
                "debt_equity": fmt_number(row.get("debt_equity"), suffix=" lần"),
                "net_margin": fmt_number(row.get("net_margin"), suffix="%"),
            }
        )

    income_rows = []
    for row in income:
        income_rows.append(
            {
                "period": row.get("period", "Không rõ"),
                "revenue": row.get("revenue_formatted") or fmt_vnd(row.get("revenue")),
                "gross_profit": row.get("gross_profit_formatted") or fmt_vnd(row.get("gross_profit")),
                "net_income": row.get("net_income_formatted") or fmt_vnd(row.get("net_income")),
                "revenue_growth_yoy": fmt_number(row.get("revenue_growth_yoy"), suffix="%"),
                "profit_growth_yoy": fmt_number(row.get("profit_growth_yoy"), suffix="%"),
                "revenue_growth_yoy_raw": row.get("revenue_growth_yoy"),
                "profit_growth_yoy_raw": row.get("profit_growth_yoy"),
            }
        )

    return {
        "raw": report_data,
        "symbol": symbol,
        "company_name": report_data.get("company_name") or "Không có dữ liệu",
        "generated_at": report_data.get("generated_at") or datetime.now().isoformat(timespec="seconds"),
        "last_price": fmt_number(technical.get("last_price"), suffix=" nghìn đồng/cp"),
        "last_date": technical.get("last_date", "Không có dữ liệu"),
        "trend": technical.get("trend", "Không có dữ liệu"),
        "rsi": fmt_number(indicators.get("rsi")),
        "pe": fmt_number(latest_ratio.get("pe")),
        "pb": fmt_number(latest_ratio.get("pb")),
        "roe": fmt_number(latest_ratio.get("roe"), suffix="%"),
        "score": score_num,
        "grade": grade,
        "score_summary": score_data.get("summary_vi", "Không có dữ liệu"),
        "sentiment": sentiment,
        "technical_rows": technical_rows,
        "active_signals": signals,
        "ratio_rows": ratio_rows,
        "income_rows": income_rows,
        "balance": {
            "year": balance.get("year", "Không rõ"),
            "total_assets": balance.get("total_assets_formatted") or fmt_vnd(balance.get("total_assets")),
            "total_debt": balance.get("total_debt_formatted") or fmt_vnd(balance.get("total_debt")),
            "equity": balance.get("equity_formatted") or fmt_vnd(balance.get("equity")),
            "cash": balance.get("cash_formatted") or fmt_vnd(balance.get("cash")),
        },
        "analysis_html": markdown_to_html(report_data.get("comprehensive_analysis")),
        "technical_llm_html": markdown_to_html(safe_get(report_data, "technical.llm_analysis", "")),
        "fundamental_llm_html": markdown_to_html(safe_get(report_data, "fundamental.llm_analysis", "")),
        "llm_fallback_used": bool(report_data.get("llm_fallback_used")),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_html(report_data: Dict[str, Any]) -> str:
    """Render báo cáo phân tích chứng khoán thành HTML hoàn chỉnh."""
    if not isinstance(report_data, dict):
        raise TypeError("report_data phải là dict")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("report.html")
    view = build_view_model(report_data)
    return template.render(**view)


def save_html(report_data: Dict[str, Any], output_path: Optional[str | Path] = None) -> str:
    """Lưu báo cáo HTML vào thư mục reports và trả về đường dẫn file."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    symbol = slugify_symbol(report_data.get("symbol"))
    path = Path(output_path) if output_path else REPORTS_DIR / f"{symbol}_{now_stamp()}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    html = render_html(report_data)
    path.write_text(html, encoding="utf-8")
    LOGGER.info("Đã lưu báo cáo HTML: %s", path)
    return str(path)


def save_pdf(report_data: Dict[str, Any], output_path: Optional[str | Path] = None) -> str:
    """Lưu báo cáo PDF bằng WeasyPrint; nếu lỗi thì fallback sang HTML kèm hướng dẫn in PDF."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    symbol = slugify_symbol(report_data.get("symbol"))
    pdf_path = Path(output_path) if output_path else REPORTS_DIR / f"{symbol}_{now_stamp()}.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    html = render_html(report_data)

    try:
        from weasyprint import HTML  # type: ignore

        HTML(string=html, base_url=str(PROJECT_ROOT)).write_pdf(str(pdf_path))
        LOGGER.info("Đã lưu báo cáo PDF: %s", pdf_path)
        return str(pdf_path)
    except Exception as exc:  # pragma: no cover - phụ thuộc môi trường OS
        LOGGER.warning("Không xuất được PDF bằng WeasyPrint: %s", exc)
        fallback_path = pdf_path.with_suffix(".html")
        guide = """
        <div class=\"print-guide no-print\">
          <h2>Không xuất được PDF tự động</h2>
          <p>Môi trường hiện tại chưa hỗ trợ WeasyPrint hoặc thiếu thư viện hệ thống.</p>
          <p>Hãy mở file HTML này trên trình duyệt, nhấn <strong>Ctrl + P</strong>, chọn <strong>Save as PDF</strong>.</p>
        </div>
        """
        html_with_guide = html.replace("</body>", guide + "</body>")
        fallback_path.write_text(html_with_guide, encoding="utf-8")
        return str(fallback_path)


def generate_report(symbol: str, format: str = "html") -> Dict[str, Any]:
    """Chạy agent.full_report(symbol), sau đó xuất HTML hoặc PDF."""
    fmt = (format or "html").lower().strip()
    if fmt not in SUPPORTED_FORMATS:
        return {
            "success": False,
            "symbol": symbol,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "error": "format chỉ hỗ trợ 'html' hoặc 'pdf'",
        }

    try:
        from agent.agent import get_agent

        report_data = get_agent().full_report(symbol)
        if isinstance(report_data, dict) and report_data.get("error"):
            return {
                "success": False,
                "symbol": symbol,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "error": report_data.get("error"),
                "report_data": report_data,
            }

        if fmt == "pdf":
            file_path = save_pdf(report_data)
        else:
            file_path = save_html(report_data)

        return {
            "success": True,
            "file_path": file_path,
            "symbol": symbol.upper(),
            "format": Path(file_path).suffix.replace(".", ""),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "llm_fallback_used": bool(report_data.get("llm_fallback_used")),
        }
    except Exception as exc:
        LOGGER.exception("Lỗi khi tạo báo cáo %s", symbol)
        return {
            "success": False,
            "symbol": symbol.upper(),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# CLI test nhanh
# ---------------------------------------------------------------------------

def _main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "FPT"
    fmt = sys.argv[2] if len(sys.argv) > 2 else "html"
    result = generate_report(symbol, fmt)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
