# AI Stock Dashboard — setup.ps1
# Chạy trong PowerShell tại thư mục project:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\setup.ps1

$ErrorActionPreference = "Stop"

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "AI Stock Dashboard — setup.ps1" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

$python = "python"

try {
    $version = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    Write-Host "Python version: $version"
} catch {
    Write-Host "Không tìm thấy Python. Hãy cài Python >= 3.10." -ForegroundColor Red
    exit 1
}

& $python -c "import sys; raise SystemExit('Python phải >= 3.10') if sys.version_info < (3,10) else print('Python OK')"

if (!(Test-Path "venv")) {
    Write-Host "Tạo virtual environment..."
    & $python -m venv venv
}

Write-Host "Kích hoạt venv..."
. .\venv\Scripts\Activate.ps1

Write-Host "Cập nhật pip..."
python -m pip install -U pip setuptools wheel

Write-Host "Cài requirements..."
python -m pip install -r requirements.txt

Write-Host "Kiểm tra Ollama..."
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue

if ($null -eq $ollamaCmd) {
    Write-Host "Chưa thấy Ollama. Tải installer tại: https://ollama.ai/download" -ForegroundColor Yellow
} else {
    Write-Host "Ollama đã được cài."

    try {
        Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 | Out-Null
        Write-Host "Ollama đang online."

        $models = ollama list
        if ($models -notmatch "llama3.2") {
            Write-Host "Chưa có model llama3.2. Đang tải..."
            ollama pull llama3.2
        }
    } catch {
        Write-Host "Ollama chưa chạy. Mở terminal khác và chạy: ollama serve" -ForegroundColor Yellow
    }
}

Write-Host "Test import nhanh..."
python -c "import importlib; mods=['technical','fundamental','agent.ollama_client','agent.agent','reporter.report_generator','ai_routes']; [print('OK:', m) or importlib.import_module(m) for m in mods]"

Write-Host ""
Write-Host "Setup xong." -ForegroundColor Green
Write-Host "Chạy dashboard: python app.py"
Write-Host "Mở browser: http://127.0.0.1:5000"
