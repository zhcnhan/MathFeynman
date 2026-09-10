# 停止 YanHui 前后端（R34 加固：按「进程树」停止，不再留下孤儿）
#
# 为什么之前不够：dev.ps1 用 Start-Process 起后端(python)与前端(cmd -> npm -> node/vite)，
# 登记的 PID 是「父进程」；只杀父进程会让真正的服务进程（vite 的 node、uvicorn 的子进程）
# 变成孤儿继续占着 8000/5173 —— 下一轮启动时端口被占、行为诡异。
# 现在：递归找出每个登记 PID 的整棵子进程树，由深到浅逐个终止。
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root ".runtime\pids.txt"

function Stop-Tree([int]$rootPid, [string]$why) {
    $all = @(Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId)
    $targets = New-Object System.Collections.Generic.List[int]
    $queue = New-Object System.Collections.Generic.Queue[int]
    $queue.Enqueue($rootPid)
    while ($queue.Count -gt 0) {
        $cur = $queue.Dequeue()
        if ($targets.Contains($cur)) { continue }
        $targets.Add($cur)
        foreach ($c in ($all | Where-Object { $_.ParentProcessId -eq $cur })) { $queue.Enqueue([int]$c.ProcessId) }
    }
    # 先子后父（避免父进程先死导致子进程脱离、ParentProcessId 被清空而找不到）
    foreach ($id in ($targets | Sort-Object -Descending)) {
        $p = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($p) {
            Write-Host "  停止 $($p.ProcessName) PID=$id  ($why)"
            Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        }
    }
    return $targets.Count
}

if (Test-Path $pidFile) {
    $killed = 0
    foreach ($line in (Get-Content $pidFile)) {
        $v = "$line".Trim()
        if ($v -match '^\d+$') { $killed += (Stop-Tree ([int]$v) "登记进程树") }
    }
    Write-Host "已停止 $killed 个进程（含子进程树）。"
} else {
    Write-Host "未找到 .runtime\pids.txt（可能不是由 dev.ps1 启动）。"
}

# 兜底：清掉可能残留的孤儿服务进程（按命令行精确匹配，只碰本项目的服务）
$leftovers = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'uvicorn app\.main|frontend\\node_modules.*vite' }
foreach ($p in $leftovers) {
    Write-Host "  清理残留 $($p.Name) PID=$($p.ProcessId)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Write-Host "停止完成。"
