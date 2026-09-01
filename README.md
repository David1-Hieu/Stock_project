# AI Stock Dashboard — AI Agent phân tích chứng khoán Việt Nam

Dự án này là một dashboard chạy local để phân tích cổ phiếu Việt Nam. Hệ thống lấy dữ liệu từ `vnstock`, tính chỉ báo kỹ thuật, đọc chỉ số cơ bản, dùng Ollama local để tạo nhận định AI, và xuất báo cáo HTML/PDF.

> Kết quả chỉ phục vụ mục đích nghiên cứu cá nhân, không phải khuyến nghị đầu tư.

---

## 1. Tính năng chính

- Lấy dữ liệu giá OHLCV cho cổ phiếu Việt Nam.
- Tính RSI, MACD, Bollinger Bands, EMA20/50/200, Volume MA20.
- Phát hiện tín hiệu kỹ thuật: RSI quá mua/quá bán, MACD cross, EMA trend, Bollinger squeeze, volume spike.
- Lấy dữ liệu cơ bản: P/E, P/B, ROE, ROA, EPS, Debt/Equity, doanh thu, lợi nhuận, bảng cân đối.
- Chấm điểm cơ bản và screening nhiều mã cổ phiếu.
- Gọi Ollama local để tạo báo cáo phân tích bằng tiếng Việt.
- Xuất báo cáo HTML/PDF.
- Flask API cho dashboard.

---

## 2. Cấu trúc thư mục

```text
Stock_analyze/
├── app.py                     # Entry point Flask application
├── ai_routes.py               # AI routes & handlers
├── batch_collect.py           # Thu thập dữ liệu hàng loạt & screening
├── technical.py               # Phân tích kỹ thuật & chỉ báo (RSI, MACD, EMA, BB, Volume)
├── fundamental.py             # Phân tích cơ bản & chỉ số tài chính (P/E, P/B, ROE, ROA)
├── requirements.txt           # Danh sách thư viện phụ thuộc
├── test_all.py                # Script kiểm thử toàn bộ hệ thống
├── setup.ps1 / setup.sh       # Script cài đặt tự động (Windows / Linux-macOS)
│
├── agent/                     # Module AI Agent & Ollama integration
│   ├── agent.py               # Agent điều phối phân tích
│   ├── chatbot.py             # Chatbot trợ lý chứng khoán
│   ├── ollama_client.py       # Kết nối Ollama API local
│   └── prompts.py             # System prompts & template phân tích
│
├── config/                    # Cấu hình hệ thống & scoring
│   └── scoring_config.json
│
├── database/                  # Quản lý SQLite database (Watchlist, Portfolio, Snapshots)
├── monitoring/                # EOD monitoring & phân tích 5 ngày
├── recommendation/            # Công cụ gợi ý & chấm điểm
├── screening/                 # Screening & scoring engine
├── services/                  # Service layer (AnalysisService)
├── routes/                    # Modular Flask blueprints (Pages, Features)
├── reporter/                  # Xuất báo cáo HTML & PDF
├── static/                    # Assets CSS & JS giao diện hiện đại
├── templates/                 # Giao diện web Jinja2 templates
└── tests/                     # Bộ unit test tự động
```


---

## 3. Yêu cầu hệ thống

- Python 3.10 trở lên.
- Khuyến nghị Python 3.10–3.12 để tương thích thư viện tốt hơn.
- Ollama để chạy LLM local.
- RAM:
  - 8GB: `llama3.2:3b` hoặc `llama3.2`
  - 16GB: `gemma3:12b` hoặc `llama3.1:8b`
  - 32GB: model lớn hơn như `mistral` hoặc model quantized

---

## 4. Cài đặt nhanh trên Windows PowerShell

Tại thư mục project:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup.ps1
```


Nếu muốn làm thủ công:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt
```

---

## 5. Cài đặt nhanh trên macOS/Linux/Git Bash

```bash
cd /path/to/project
chmod +x setup.sh
./setup.sh
```

Hoặc thủ công:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt
```

---

## 6. Cài và chạy Ollama

Cài Ollama:

```bash
# macOS/Linux
curl -fsSL https://ollama.ai/install.sh | sh
```

Windows: tải installer tại trang Ollama.

Khởi động Ollama:

```powershell
ollama serve
```

Tải model:

```powershell
ollama pull llama3.2
```

Kiểm tra:

```powershell
ollama list
curl http://localhost:11434/api/tags
```

---

## 7. Chạy dashboard

```powershell
.\venv\Scripts\Activate.ps1
python app.py
```

Mở trình duyệt:

```text
http://127.0.0.1:5000
```

### Modern Dashboard UI

Dashboard được thiết kế lại hoàn toàn với phong cách tối (Dark mode) hiện đại mang cảm hứng từ các sàn giao dịch tài chính/blockchain chuyên nghiệp:

* **Cách chạy**:
  ```powershell
  python app.py
  ```
* **Địa chỉ truy cập**:
  ```text
  http://127.0.0.1:5000
  ```
* **Các tính năng nổi bật**:
  * **Trực quan hóa trạng thái Ollama**: Kiểm tra nhanh trạng thái kết nối Ollama local, hiển thị danh sách các model và gợi ý model tối ưu bằng các nhãn màu động.
  * **Phân tích đa chiều dạng Tab**: Trình bày thông tin Phân tích kỹ thuật (RSI, MACD, Bollinger Bands, các đường EMA, Tín hiệu kích hoạt), Phân tích cơ bản (P/E, P/B, ROE, ROA, EPS, D/E, doanh thu & lợi nhuận) và Nhận định của AI Agent trong các tab riêng biệt, giúp dễ dàng theo dõi.
  * **Bảng xếp hạng (Screening)**: Hiển thị danh sách cổ phiếu dưới dạng bảng giao dịch chuyên nghiệp thay vì JSON thô, với các nhãn xu hướng màu sắc (Xanh: TĂNG, Đỏ: GIẢM, Vàng: SIDEWAY), nhãn xếp hạng (Grade A/B/C/D), và hành động nhanh (Phân tích, Báo cáo) cho mỗi dòng.
  * **Trải nghiệm người dùng mượt mà**: Sử dụng các loading skeletons khi tải dữ liệu, tắt/mở nút bấm hợp lý để tránh spam API, hiển thị thông báo Toast nhanh gọn khi có thành công hoặc lỗi phát sinh.
  * **Độ tương thích cao**: Giữ nguyên 100% logic backend, các API endpoints và hành vi hoạt động gốc để đảm bảo hệ thống luôn ổn định và vượt qua mọi bài kiểm thử.

---

## 8. Chạy screening nhiều cổ phiếu

Test 3 mã:

```powershell
python batch_collect.py --symbols FPT,VCB,VNM --delay 6
```

Chạy VN30 giới hạn 5 mã:

```powershell
python batch_collect.py --universe VN30 --limit 5 --delay 6
```

Chạy toàn VN30:

```powershell
python batch_collect.py --universe VN30 --delay 6
```

Nếu gặp rate limit, tăng delay:

```powershell
python batch_collect.py --universe VN30 --delay 10
```

Quét nhanh chỉ technical:

```powershell
python batch_collect.py --universe VN30 --no-fundamental --delay 3
```

Kết quả được lưu vào:

```text
batch_results/stock_screening_YYYYMMDD_HHMM.csv
batch_results/stock_screening_YYYYMMDD_HHMM.json
```

---

## 9. Tạo báo cáo

Tạo HTML:

```powershell
python -m reporter.report_generator FPT html
```

Tạo PDF:

```powershell
python -m reporter.report_generator FPT pdf
```

Nếu WeasyPrint lỗi trên Windows, mở file HTML rồi dùng:

```text
Ctrl + P → Save as PDF
```

Báo cáo nằm trong:

```text
reports/
```

---

## 10. API endpoints

### Kiểm tra Ollama

```http
GET /api/agent/status
```

### Phân tích cổ phiếu

```http
GET /api/analysis/<symbol>?type=technical
GET /api/analysis/<symbol>?type=fundamental
GET /api/analysis/<symbol>?type=full
```

Ví dụ:

```text
http://127.0.0.1:5000/api/analysis/FPT?type=full
```

### Tạo báo cáo

```http
GET /api/report/<symbol>?format=html
GET /api/report/<symbol>?format=pdf
```

Ví dụ:

```text
http://127.0.0.1:5000/api/report/VCB?format=html
```

### Mở báo cáo đã tạo

```http
GET /reports/<filename>
```

### Tải ranking mới nhất

```http
GET /api/screening/latest
```

### Tổng quan danh mục

```http
POST /api/portfolio/overview
```

Với dashboard test chưa có holdings thật, endpoint này có thể báo chưa có danh mục. Có thể gửi body JSON để test:

```json
{
  "holdings": [
    {"symbol": "FPT", "quantity": 100, "avg_cost": 70, "current_price": 72.3, "pl_percent": 3.28},
    {"symbol": "VCB", "quantity": 100, "avg_cost": 60, "current_price": 62, "pl_percent": 3.33}
  ]
}
```

---

## 11. Kiểm thử

Chạy test cơ bản:

```powershell
python test_all.py all
```

Chạy từng phần:

```powershell
python test_all.py technical
python test_all.py fundamental
python test_all.py ollama
python test_all.py flask
python test_all.py batch
```

Chạy full pipeline, có gọi Ollama và mất lâu hơn:

```powershell
python test_all.py full --symbol FPT
```

Test tạo report:

```powershell
python test_all.py report --symbol FPT --format html
```

---

## 12. Troubleshooting

### `ModuleNotFoundError: No module named 'vnstock'`

Cài lại dependency vào đúng môi trường:

```powershell
python -m pip install -U vnstock
```

### `ModuleNotFoundError: No module named 'agent'`

Hãy chạy lệnh từ thư mục gốc project:

```powershell
python app.py
```

Không chạy từ bên trong folder `agent` hoặc `reporter`.

### Ollama offline

Chạy:

```powershell
ollama serve
```

Rồi kiểm tra:

```powershell
curl http://localhost:11434/api/tags
```

### Ollama timeout

Dùng model nhẹ hơn:

```powershell
ollama pull llama3.2:3b
```

Sau đó đổi model mặc định trong `agent/ollama_client.py` nếu cần.

### vnstock rate limit

Tăng delay khi chạy batch:

```powershell
python batch_collect.py --universe VN30 --delay 10
```

Hoặc đăng ký Community API key theo hướng dẫn của vnstock.

### WeasyPrint lỗi khi xuất PDF

Vẫn tạo HTML được. Mở HTML bằng trình duyệt rồi:

```text
Ctrl + P → Save as PDF
```

---

## 13. Quy trình khuyến nghị hằng ngày

1. Bật Ollama:

```powershell
ollama serve
```

2. Chạy batch screening:

```powershell
python batch_collect.py --symbols FPT,VCB,VNM --delay 6
```

3. Chạy dashboard:

```powershell
python app.py
```

4. Mở:

```text
http://127.0.0.1:5000
```

5. Tải ranking mới nhất.
6. Chỉ gọi AI full report cho mã cần xem kỹ.

---

## 14. Miễn trừ trách nhiệm

Dự án chỉ phục vụ mục đích học tập, nghiên cứu cá nhân và thử nghiệm AI Agent. Không xem bất kỳ kết quả nào là khuyến nghị đầu tư, tư vấn tài chính hoặc lời mời mua/bán chứng khoán.
