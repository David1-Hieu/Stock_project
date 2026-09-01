# Stock_analyze v2 — Multi-Factor Screening Upgrade

Bản nâng cấp này phát triển trực tiếp từ workflow của project gốc: `technical.py` + `fundamental.py` → `batch_collect.py` → `batch_results` → dashboard.

## 1. Điểm mới

Hệ thống không còn dùng một điểm trộn đơn giản giữa fundamental và technical. Mỗi cổ phiếu có 4 điểm độc lập:

- **Fundamental Score**: ROE, ROA, tăng trưởng doanh thu, tăng trưởng lợi nhuận, biên LN ròng, EPS.
- **Valuation Score**: P/E + P/B, có profile cơ bản theo BANK / SECURITIES / REAL_ESTATE / DEFAULT.
- **Technical Score**: trend, EMA structure, RSI, MACD, technical signals, volume spike.
- **Risk Score**: điểm an toàn (cao = an toàn hơn) dựa trên D/E, debt/assets, lợi nhuận, EMA200, RSI và Bollinger width proxy.

Điểm cuối:

`Final = 30% Fundamental + 25% Valuation + 25% Technical + 20% Risk`

Trọng số nằm trong `config/scoring_config.json`, có thể thay đổi mà không sửa logic Python.

## 2. Hard filters

Mặc định hệ thống đánh dấu `eligible = false` nếu:

- EPS <= 0;
- lợi nhuận ròng kỳ gần nhất <= 0;
- dữ liệu quá thiếu.

Cổ phiếu bị fail vẫn giữ `final_score` để chẩn đoán, nhưng được xếp sau các mã eligible.

## 3. Cài vào project gốc

Sao lưu project trước. Sau đó copy các file/thư mục sau vào root project:

- `batch_collect.py` (ghi đè file cũ)
- `screening/`
- `config/`
- `tests/test_scoring_engine.py`

Không cần sửa `technical.py` hoặc `fundamental.py` ở phase này.

## 4. Test scoring engine không cần internet

Tại root project:

```powershell
python -m unittest tests.test_scoring_engine -v
```

## 5. Test 3 mã với dữ liệu thật

```powershell
python batch_collect.py --symbols FPT,VCB,VNM --delay 6
```

Nếu cache cũ gây nhiễu:

```powershell
python batch_collect.py --symbols FPT,VCB,VNM --delay 6 --force-refresh
```

## 6. Chạy VN30

```powershell
python batch_collect.py --universe VN30 --limit 5 --delay 6
python batch_collect.py --universe VN30 --delay 6
```

## 7. Output mới

CSV/JSON trong `batch_results/` có thêm:

- `final_score`
- `fundamental_score`
- `valuation_score`
- `technical_score`
- `risk_score`
- `eligible`
- `action`
- `filter_reasons`
- `score_explanation`
- `scoring_v2` (JSON chi tiết từng breakdown)

`screening_score` vẫn được giữ và bằng `final_score` để dashboard/API cũ không bị gãy.

## 8. Lưu ý về Risk Score

Ở phase này Risk Score là **risk/safety proxy** vì batch summary của project gốc chưa truyền cả chuỗi return lịch sử. Phase tiếp theo nên mở rộng `technical.py` để tính:

- realized volatility 20/60/252 phiên;
- max drawdown;
- downside volatility;
- beta so với VNIndex;
- relative strength so với VNIndex/VN30;
- average trading value/liquidity.

Sau đó có thể thay thế proxy hiện tại mà không đổi schema của `scoring_v2`.

## 9. Roadmap tiếp theo

1. Backtest top-N ranking so với VNIndex.
2. Thêm VNIndex/VN30 Market Regime.
3. Thêm Relative Strength.
4. Thu thập news theo ticker.
5. PhoBERT sentiment.
6. Kết hợp news score vào final ranking.
