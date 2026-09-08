# MathFeynman 一键启动（Windows，docs/02 §4 / docs/08 M0）
# 用法:  .\scripts\dev.ps1 [-SkipBrowser] [-SkipInstall]
param(
    [switch]$SkipBrowser,
    [switch]$SkipInstall,
    [int]$BackendPort = 8000,
    [int]$FrontPort = 5173
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv"
$runtime = Join-Path $root ".runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$pyExe = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $pyExe)) {
    Write-Host "[1/4] 创建 venv: $venv"
    python -m venv $venv
}

if (-not $SkipInstall) {
    Write-Host "[2/4] 安装后端依赖 (pip install -e backend)"
    & $pyExe -m pip install -e (Join-Path $root "backend") -q
    if ($LASTEXITCODE -ne 0) { throw "后端依赖安装失败" }
    if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
        Write-Host "[2/4] 安装前端依赖 (npm install)"
        Push-Location (Join-Path $root "frontend")
        try { npm install --no-fund --no-audit; if ($LASTEXITCODE -ne 0) { throw "前端依赖安装失败" } }
        finally { Pop-Location }
    }
}

Write-Host "[3/4] 启动后端 uvicorn (127.0.0.1:$BackendPort)"
$backend = Start-Process -FilePath $pyExe -ArgumentList @(
    "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort"
) -WorkingDirectory (Join-Path $root "backend") `
    -RedirectStandardOutput (Join-Path $runtime "backend.out.log") `
    -RedirectStandardError (Join-Path $runtime "backend.err.log") `
    -WindowStyle Hidden -PassThru

Write-Host "[4/4] 启动前端 vite dev (http://127.0.0.1:$FrontPort)"
# npm 实为 npm.cmd，须经 cmd.exe 启动（保证重定向与退出码）
$front = Start-Process -FilePath "cmd.exe" -ArgumentList @(
    "/c", "npm run dev -- --port $FrontPort"
) -WorkingDirectory (Join-Path $root "frontend") `
    -RedirectStandardOutput (Join-Path $runtime "front.out.log") `
    -RedirectStandardError (Join-Path $runtime "front.err.log") `
    -WindowStyle Hidden -PassThru

# 记录 PID 供 stop.ps1 使用
@("$($backend.Id)", "$($front.Id)") | Set-Content (Join-Path $runtime "pids.txt")
Start-Sleep -Seconds 6
Write-Host "后端 PID=$($backend.Id)  前端 PID=$($front.Id)"
if (-not $SkipBrowser) { Start-Process "http://127.0.0.1:$FrontPort" }
Write-Host "已启动。浏览器打开 http://127.0.0.1:$FrontPort （后端 $BackendPort，日志在 .runtime/）"
Write-Host "停止: .\scripts\stop.ps1"
