#!/usr/bin/env bash
set -e

echo "=============================================="
echo "AI Stock Dashboard — setup.sh"
echo "=============================================="

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Không tìm thấy python3. Hãy cài Python >= 3.10."
  exit 1
fi

PY_VERSION=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python version: $PY_VERSION"

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python phải >= 3.10")
print("Python OK")
PY

if [ ! -d "venv" ]; then
  echo "Tạo virtual environment..."
  "$PYTHON_BIN" -m venv venv
fi

echo "Kích hoạt venv..."
# shellcheck disable=SC1091
source venv/bin/activate

echo "Cập nhật pip..."
python -m pip install -U pip setuptools wheel

echo "Cài requirements..."
python -m pip install -r requirements.txt

echo "Kiểm tra Ollama..."
if command -v ollama >/dev/null 2>&1; then
  echo "Ollama đã được cài."
  if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "Ollama chưa chạy. Mở terminal khác và chạy: ollama serve"
  else
    echo "Ollama đang online."
  fi

  if ! ollama list | grep -q "llama3.2"; then
    echo "Chưa có model llama3.2. Đang tải..."
    ollama pull llama3.2
  fi
else
  echo "Chưa thấy Ollama."
  echo "Cài macOS/Linux: curl -fsSL https://ollama.ai/install.sh | sh"
  echo "Windows: tải installer tại https://ollama.ai/download"
fi

echo "Test import nhanh..."
python - <<'PY'
import importlib
mods = ["technical", "fundamental", "agent.ollama_client", "agent.agent", "reporter.report_generator", "ai_routes"]
for mod in mods:
    importlib.import_module(mod)
    print("OK:", mod)
PY

echo ""
echo "Setup xong."
echo "Chạy dashboard: python app.py"
echo "Mở browser: http://127.0.0.1:5000"
