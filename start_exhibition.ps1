$ErrorActionPreference = "Stop"

$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectDirectory

$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $pythonCommand) {
    Write-Host "Pythonが見つかりません。Python 3.11以降をインストールしてください。" -ForegroundColor Red
    Read-Host "Enterキーで終了"
    exit 1
}

Write-Host "依存ライブラリを確認しています..." -ForegroundColor Cyan
& $pythonCommand.Source -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ollamaReady = $false
try {
    Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null
    $ollamaReady = $true
} catch {}

if (-not $ollamaReady) {
    $ollamaPath = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path -LiteralPath $ollamaPath) {
        Write-Host "Ollamaを起動しています..." -ForegroundColor Cyan
        Start-Process -FilePath $ollamaPath -ArgumentList 'serve' -WindowStyle Hidden
    }
}

Start-Process "http://127.0.0.1:8765" -WindowStyle Hidden
Write-Host "展示を開始します。終了するときは Ctrl+C を押してください。" -ForegroundColor Green
& $pythonCommand.Source exhibition_server.py
