@echo off
powershell.exe -NoProfile -Command "New-Item -ItemType File -Force -Path '%~dp0data\.stop-kiosk' | Out-Null"
