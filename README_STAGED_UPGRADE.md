# Stock_analyze v3 — Staged Upgrade

Bản này được thiết kế để **nâng cấp trên project gốc**, không thay đổi `technical.py`, `fundamental.py`, `ai_routes.py`, `reporter/` hay Ollama client hiện có.

## Stage 0 — Multi-factor Scoring

- `screening/scoring_engine.py`
- `config/scoring_config.json`
- `batch_collect.py` V2-compatible
- Fundamental / Valuation / Technical / Risk / Final Score
- Hard filter + explainability

## Stage 1 — Multi-page UI

Các trang riêng:

- `/` Dashboard
- `/screener`
- `/analysis/<symbol>`
- `/watchlist`
- `/portfolio`
- `/ai-reports`
- `/settings`
- `/legacy` vẫn mở UI cũ nếu `templates/index.html` còn tồn tại.

Chatbot là floating bubble cố định **góc phải dưới** trên mọi page.

## Stage 2 — Watchlist + Portfolio + SQLite

Database mặc định: `data/stock_analyze.db`.

Các bảng:

- `watchlist`
- `holdings`
- `daily_snapshots`
- `recommendations`
- `chat_history`

Watchlist khác Portfolio: Watchlist = đang quan tâm; Portfolio = đang nắm giữ.

## Stage 3 — EOD Monitor + 5-session Analyzer

Chạy thủ công:

```powershell
python -m monitoring.run_eod
```

Mỗi lần chạy:

1. Capture `VNINDEX`, `VN30`.
2. Capture toàn bộ mã ACTIVE trong Watchlist.
3. Upsert theo `trade_date`, vì vậy chạy lại cùng một phiên không nhân đôi dữ liệu.
4. Khi một mã có đủ 5 phiên, tính:
   - 5D return
   - volatility
   - max drawdown
   - Relative Strength vs VNIndex/VN30
   - thay đổi RSI / Technical Score
5. `recommendation/engine.py` sinh system action.

Scheduler tự động:

```powershell
python -m monitoring.scheduler
```

Mặc định Thứ 2–Thứ 6 lúc 15:30 giờ Việt Nam. Ngày nghỉ không tạo phiên giả vì snapshot lấy `trade_date` thật từ nguồn dữ liệu.

## Stage 4 — Ollama context-aware chatbot

`agent/chatbot.py` đọc:

- page hiện tại
- symbol hiện tại
- Watchlist
- Portfolio
- latest screening
- latest EOD snapshot
- latest 5-session recommendation

**Ollama chỉ giải thích**. Tín hiệu hành động được tạo bởi Python `Recommendation Engine`, không phải do LLM tự suy đoán.

## Cài vào project hiện tại

Giải nén upgrade ra ngoài project gốc. Ví dụ:

```text
C:\Stock_analyze-main\
C:\Stock_analyze_v3_staged_upgrade\
```

Chạy:

```powershell
cd C:\Stock_analyze_v3_staged_upgrade
python install_upgrade.py --project-root "C:\Stock_analyze-main"
```

Installer:

- backup `app.py`, `batch_collect.py`, `requirements.txt` khi cần;
- không xóa `technical.py`, `fundamental.py`, `ai_routes.py`, frontend cũ;
- tạo SQLite schema;
- thêm APScheduler vào requirements.

Sau đó:

```powershell
cd C:\Stock_analyze-main
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py" -v
python app.py
```

Mở `http://127.0.0.1:5000`.

## Quy trình test khuyến nghị

### 1. Scoring

```powershell
python batch_collect.py --symbols FPT,VCB,VNM --delay 6
```

### 2. Watchlist

Mở `/screener` → `+ Watchlist`.

### 3. EOD

```powershell
python -m monitoring.run_eod
```

Cần 5 ngày giao dịch thực tế để có recommendation 5 phiên. Trong quá trình phát triển có thể unit-test analyzer bằng dữ liệu mock.

### 4. Chatbot

```powershell
ollama serve
python app.py
```

Mở `/analysis/HPG`, bấm bubble `AI` ở trái dưới và hỏi “Mã này đang mạnh hay yếu so với VNIndex?”.

## Lưu ý về dữ liệu chỉ số

`monitoring.daily_snapshot` gọi `load_ohlcv("VNINDEX")` và `load_ohlcv("VN30")` qua data provider hiện hữu. Nếu provider vnstock bạn đang dùng không chấp nhận một trong hai symbol này, hãy map symbol index trong `monitoring/daily_snapshot.py` theo provider thực tế. Lỗi benchmark không làm mất snapshot các mã cổ phiếu; `run_eod` ghi lỗi riêng trong `errors`.

## Nguyên tắc thiết kế

```text
Quant/Data Engine -> Score/Signals -> Recommendation Engine -> Ollama explanation
```

Không dùng LLM làm nguồn giá, không cho LLM tự tạo dữ liệu, và không coi output là tư vấn đầu tư cá nhân hóa.


## Chatbot close fix
- Chat panel now respects the HTML `hidden` attribute via `.chat-panel[hidden]{display:none!important}`.
- The close button, chat bubble toggle, and Escape key all close the panel.

## Dedicated Analysis page (updated)

V3 now includes a dedicated `/analysis/<symbol>` page that restores the structured analysis experience of the original project instead of showing raw JSON only.

- Navigation: `Analysis` -> `/analysis` (defaults to FPT)
- Technical tab: latest price/date, RSI, MACD/Signal/Histogram, EMA20/50/200, Bollinger Bands, Volume MA20, active signals, and a 90-session close-price chart.
- Fundamental tab: P/E, P/B, ROE, ROA, EPS, Debt/Equity, Net Margin, fundamental score/grade, score breakdown, income history and balance sheet.
- 5 Sessions and AI Analysis remain separate tabs.
- Raw technical/fundamental data continue to come from the original `technical.py` and `fundamental.py` through `/api/raw-analysis/<symbol>`.

## V3.1 - Analysis page fix for arbitrary tickers

Analysis no longer depends on the latest `batch_results/stock_screening_*.json` to obtain Final / Valuation / Technical / Risk scores. The page now calls `/api/analysis-data/<symbol>` and scores the requested ticker on demand.

Technical loading was also consolidated. The old page requested technical summary and chart separately, causing multiple simultaneous vnstock OHLCV downloads for the same ticker. V3.1 downloads a sufficiently long OHLCV history once, then reuses it for EMA200, RSI, MACD, Bollinger Bands, signals and the chart. If a provider still fails, the exact backend error is shown in the Analysis status banner.

## V3.2 - Watchlist snapshot fix

- Khi thêm mã từ trang Analysis, hệ thống lưu ngay snapshot phân tích hiện tại vào SQLite.
- Watchlist có thể hiển thị `Close` và `Final Score` ngay, không cần chờ EOD cho snapshot đầu tiên.
- EOD monitor không còn lấy score từ `batch_results`; score được tính trực tiếp cho từng mã Watchlist.
- Thêm mã thủ công từ trang Watchlist vẫn hợp lệ, nhưng cần chạy EOD/Analysis để có dữ liệu thị trường.


## V3.3 - Watchlist 5D Average Close

- Cột `5D` trên Watchlist được đổi thành `TB Close 5D`.
- Giá trị là trung bình số học của **5 giá đóng cửa gần nhất** đã lưu trong `daily_snapshots`.
- `return_5d` vẫn được giữ trong Five-Day Analyzer để tính Relative Strength và Recommendation; chỉ cách hiển thị cột Watchlist thay đổi.
- Watchlist tính `five_day_analysis` trực tiếp từ snapshot nên không cần chờ recommendation được lưu mới thấy TB Close 5D.
