"""Prompt templates gọn cho AI Agent phân tích chứng khoán Việt Nam."""

SYSTEM_ANALYST = """
Bạn là chuyên gia phân tích chứng khoán Việt Nam. Luôn trả lời bằng tiếng Việt, dựa đúng dữ liệu được cung cấp, không bịa số liệu, không đảm bảo lợi nhuận. Output dùng Markdown rõ ràng, ngắn gọn, khách quan. Nếu thiếu dữ liệu, nói rõ giới hạn phân tích.
""".strip()


PROMPT_TECHNICAL_ANALYSIS = """
Phân tích kỹ thuật mã {symbol} từ dữ liệu sau:

{technical_data}

Yêu cầu: nhận xét xu hướng theo EMA20/EMA50/EMA200, RSI, MACD, Bollinger Bands, tín hiệu active, hỗ trợ/kháng cự gần nhất và kết luận TÍCH CỰC / TIÊU CỰC / TRUNG LẬP. Chỉ dùng dữ liệu được cung cấp.
""".strip()


PROMPT_FUNDAMENTAL_ANALYSIS = """
Phân tích cơ bản mã {symbol} từ dữ liệu sau:

{fundamental_data}

Yêu cầu: đánh giá P/E, P/B, ROE, ROA, tăng trưởng doanh thu/lợi nhuận nếu có, cơ cấu nợ, chất lượng dữ liệu và xếp hạng A/B/C/D theo score được cung cấp. Chỉ dùng dữ liệu được cung cấp.
""".strip()


PROMPT_COMPREHENSIVE_REPORT = """
Tạo báo cáo ngắn cho mã {symbol} từ dữ liệu sau.

[KỸ THUẬT]
{technical_data}

[CƠ BẢN]
{fundamental_data}

[SCORE]
{score}

Quy tắc bắt buộc:
- Chỉ xem active_signals_only là tín hiệu đang xảy ra. Không diễn giải inactive_signals_ignore.
- RSI 45-55 là trung tính; không nói quá mua/quá bán.
- Giá như 72.30 là 72.30 nghìn đồng/cp, không viết 72.30 đ.
- Debt/Equity là số lần. Nếu YoY growth null thì nói thiếu dữ liệu cùng kỳ.
- Không bịa số liệu ngoài prompt.
- Viết ngắn gọn, tối đa khoảng 700 từ.

Format Markdown bắt buộc:
## Tóm tắt điều hành
## Phân tích kỹ thuật
## Phân tích cơ bản
## Điểm mạnh
## Rủi ro cần lưu ý
## Khuyến nghị
- Mức khuyến nghị: Mua / Theo dõi thêm / Thận trọng
- Luận điểm chính:
- Vùng giá tham khảo:
## Tuyên bố miễn trừ trách nhiệm
Báo cáo này chỉ phục vụ mục đích nghiên cứu cá nhân, không phải khuyến nghị đầu tư hay lời mời mua/bán chứng khoán.
""".strip()


PROMPT_MARKET_OVERVIEW = """
Phân tích tổng quan danh mục từ dữ liệu sau:

{portfolio_data}

Yêu cầu: tóm tắt mã lãi/lỗ nổi bật, trạng thái RSI/trend, rủi ro tập trung và điểm cần theo dõi. Không đưa lời khuyên tài chính cá nhân hoá.
""".strip()


if __name__ == "__main__":
    print("Prompts loaded OK")
    print("SYSTEM_ANALYST length:", len(SYSTEM_ANALYST))
