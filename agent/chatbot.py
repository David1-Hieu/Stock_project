"""Context-aware Ollama chatbot for the multi-page dashboard."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from database import (
    append_chat,
    get_holdings,
    get_latest_recommendation,
    get_latest_snapshot,
    get_recent_chat,
    get_watchlist,
)
from monitoring.data_helpers import latest_screening_row

try:
    from agent.ollama_client import OllamaConnectionError, get_client
except ImportError:
    from ollama_client import OllamaConnectionError, get_client  # type: ignore

SYSTEM_CHAT = """
Bạn là AI Investment Assistant cho hệ thống Stock Analyze tại thị trường chứng khoán Việt Nam.
Luôn trả lời bằng tiếng Việt, ngắn gọn và dựa đúng dữ liệu CONTEXT được cung cấp.
Không bịa giá, chỉ số hoặc sự kiện. Nếu dữ liệu thiếu/hết hạn, nói rõ cần cập nhật.
Quy tắc quan trọng: tín hiệu BUY/HOLD/WATCH/REDUCE phải xuất phát từ Recommendation Engine trong context.
Bạn không được tự tạo tín hiệu giao dịch mới chỉ từ trực giác LLM. Bạn có thể giải thích, so sánh, nêu rủi ro và đề xuất bước kiểm tra tiếp theo.
Không đảm bảo lợi nhuận. Kết thúc các câu trả lời có tính hành động bằng một lưu ý ngắn rằng đây là công cụ hỗ trợ nghiên cứu.
""".strip()


def build_context(page: str = "", symbol: str = "") -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    context: Dict[str, Any] = {
        "current_page": page,
        "current_symbol": symbol or None,
        "watchlist": get_watchlist(),
        "portfolio": get_holdings(),
    }
    if symbol:
        context["latest_screening"] = latest_screening_row(symbol)
        context["latest_snapshot"] = get_latest_snapshot(symbol)
        context["latest_recommendation"] = get_latest_recommendation(symbol)
    return context


def ask(message: str, page: str = "", symbol: str = "") -> Dict[str, Any]:
    message = message.strip()
    if not message:
        return {"success": False, "error": "Câu hỏi không được để trống."}
    context = build_context(page=page, symbol=symbol)
    history = get_recent_chat(limit=6)
    messages = [{"role": "system", "content": SYSTEM_CHAT}]
    for item in history:
        role = item.get("role")
        if role in {"user", "assistant"} and item.get("content"):
            messages.append({"role": role, "content": str(item["content"])[:2500]})
    user_content = (
        "CONTEXT JSON:\n" + json.dumps(context, ensure_ascii=False, default=str)[:12000]
        + "\n\nCÂU HỎI NGƯỜI DÙNG:\n" + message
    )
    messages.append({"role": "user", "content": user_content})
    append_chat("user", message, page=page, symbol=symbol)
    try:
        answer = get_client().chat(messages, temperature=0.2, max_tokens=800, timeout=180, max_attempts=1)
    except OllamaConnectionError as exc:
        return {"success": False, "error": str(exc), "hint": "Chạy: ollama serve"}
    append_chat("assistant", answer, page=page, symbol=symbol)
    return {"success": True, "answer": answer, "context": context}
