param(
    [string]$AppPath = (Join-Path $PSScriptRoot 'unity\RikuDesktop\Builds\Windows\RikuDesktop.exe')
)

$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python環境がありません。先に .venv を作り、pip install -r requirements.txt を実行してください。'
}
if (-not (Test-Path -LiteralPath $AppPath)) {
    throw "Unityアプリが見つかりません: $AppPath。UnityでWindows版をBuilds/Windows/RikuDesktop.exeにビルドしてください。"
}

$backendProcess = $null
try {
    try {
        Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8765/api/bootstrap' -TimeoutSec 2 | Out-Null
    }
    catch {
        $backendProcess = Start-Process -FilePath $pythonPath -ArgumentList 'exhibition_server.py' `
            -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
        $ready = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            Start-Sleep -Seconds 1
            try {
                Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8765/api/bootstrap' -TimeoutSec 2 | Out-Null
                $ready = $true
                break
            }
            catch {
                if ($backendProcess.HasExited) { break }
            }
        }
        if (-not $ready) { throw '会話サーバーを起動できませんでした。OllamaとVOICEVOXの状態を確認してください。' }
    }
    Start-Process -FilePath $AppPath -WorkingDirectory (Split-Path -Parent $AppPath) -Wait
}
finally {
    if ($backendProcess -and -not $backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id
    }
}
