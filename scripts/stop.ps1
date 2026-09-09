# 停止 YanHui 前后端（读取 .runtime/pids.txt 中记录的 PID）
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root ".runtime\pids.txt"
if (Test-Path $pidFile) {
    Get-Content $pidFile | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Write-Host "已停止记录的进程。"
} else {
    Write-Host "未找到 .runtime/pids.txt（可能不是由 dev.ps1 启动）。"
}
