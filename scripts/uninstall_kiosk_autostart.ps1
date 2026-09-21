$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "CultureFestivalAI-Kiosk.lnk"
Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
Write-Output $shortcutPath
