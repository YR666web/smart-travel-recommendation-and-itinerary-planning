param(
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action = 'start'
)

$ErrorActionPreference = 'Stop'
trap {
    Write-Host "操作失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $projectRoot 'frontend'
$runtimeRoot = Join-Path $projectRoot 'storage'
$logRoot = Join-Path $runtimeRoot 'logs'
$stateFile = Join-Path $runtimeRoot 'platform-processes.json'
$backendUrl = 'http://127.0.0.1:8000/health'
$frontendUrl = 'http://127.0.0.1:5173/'

function Get-PlatformState {
    if (-not (Test-Path -LiteralPath $stateFile)) { return $null }
    try { return Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json }
    catch { throw "启动记录损坏：$stateFile" }
}

function Get-OwnedProcess($record) {
    if ($null -eq $record) { return $null }
    $process = Get-Process -Id ([int]$record.Id) -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    try {
        if ($process.StartTime.ToUniversalTime().Ticks -eq [long]$record.StartTicks) {
            return $process
        }
    } catch { return $null }
    return $null
}

function Stop-OwnedProcess($record) {
    $process = Get-OwnedProcess $record
    if ($null -ne $process) {
        Stop-Process -Id $process.Id -Force
        Write-Host "已停止进程 $($process.Id)"
    }
}

function Test-TcpEndpoint([string]$server, [int]$port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect($server, $port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($result)
        return $true
    } catch { return $false }
    finally { $client.Close() }
}

function Test-HttpReady([string]$url) {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch { return $false }
}

function Wait-ForService([string]$url, [int]$seconds, [int]$processId) {
    $deadline = (Get-Date).AddSeconds($seconds)
    do {
        if (Test-HttpReady $url) { return $true }
        if ($null -eq (Get-Process -Id $processId -ErrorAction SilentlyContinue)) { return $false }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    return $false
}

function New-ProcessRecord($process) {
    return @{ Id = $process.Id; StartTicks = $process.StartTime.ToUniversalTime().Ticks }
}

if ($Action -eq 'status') {
    $state = Get-PlatformState
    if ($null -eq $state) { Write-Host '平台未由启动脚本运行。'; exit 0 }
    Write-Host "后端：$(if (Get-OwnedProcess $state.Backend) { '运行中' } else { '未运行' })"
    Write-Host "前端：$(if (Get-OwnedProcess $state.Frontend) { '运行中' } else { '未运行' })"
    exit 0
}

if ($Action -eq 'stop') {
    $state = Get-PlatformState
    if ($null -eq $state) { Write-Host '没有需要停止的平台进程。'; exit 0 }
    Stop-OwnedProcess $state.Frontend
    Stop-OwnedProcess $state.Backend
    Remove-Item -LiteralPath $stateFile -Force
    Write-Host '平台已停止。'
    exit 0
}

$state = Get-PlatformState
if ($null -ne $state) {
    if ((Get-OwnedProcess $state.Backend) -and (Get-OwnedProcess $state.Frontend) -and
        (Test-HttpReady $backendUrl) -and (Test-HttpReady $frontendUrl)) {
        Write-Host "平台已经运行：$frontendUrl"
        Start-Process $frontendUrl
        exit 0
    }
    Stop-OwnedProcess $state.Frontend
    Stop-OwnedProcess $state.Backend
    Remove-Item -LiteralPath $stateFile -Force
}

$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$vite = Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) {
    throw '缺少 .env。请先复制 .env.example 为 .env，并填写 MySQL 和 API 配置。'
}
if (-not (Test-Path -LiteralPath $python)) {
    throw '缺少 Python 虚拟环境。请先运行 python -m venv .venv，再运行 .venv\Scripts\python.exe -m pip install -e .'
}
if (-not (Test-Path -LiteralPath $vite)) {
    throw '缺少前端依赖。请先在 frontend 目录运行 npm ci。'
}
$node = Get-Command node -ErrorAction SilentlyContinue
if ($null -eq $node) { throw '未找到 Node.js。请先安装 Node.js。' }
$databaseEndpoint = & $python -c 'from app.config import settings; print(settings.mysql_host); print(settings.mysql_port)'
if ($LASTEXITCODE -ne 0 -or $databaseEndpoint.Count -ne 2) {
    throw '无法读取 .env 中的 MySQL 配置。'
}
if (-not (Test-TcpEndpoint $databaseEndpoint[0] ([int]$databaseEndpoint[1]))) {
    throw '无法连接 .env 中配置的 MySQL。请先启动数据库，并检查 MYSQL_HOST 和 MYSQL_PORT。'
}
foreach ($port in @(8000, 5173)) {
    if (Test-TcpEndpoint '127.0.0.1' $port) { throw "端口 $port 已被其他程序占用，请先释放该端口。" }
}

New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backend = $null
$frontend = $null
try {
    Write-Host '正在启动后端（首次加载模型可能需要几分钟）...'
    $backend = Start-Process -FilePath $python -ArgumentList '-m uvicorn app.main:app --host 127.0.0.1 --port 8000' `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot "backend-$stamp.out.log") `
        -RedirectStandardError (Join-Path $logRoot "backend-$stamp.err.log")
    if (-not (Wait-ForService $backendUrl 180 $backend.Id)) {
        throw "后端未能启动。请查看 $logRoot 中的 backend-$stamp.err.log，并确认 MySQL 已启动。"
    }

    Write-Host '正在启动前端...'
    $frontend = Start-Process -FilePath $node.Source -ArgumentList 'node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort' `
        -WorkingDirectory $frontendRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot "frontend-$stamp.out.log") `
        -RedirectStandardError (Join-Path $logRoot "frontend-$stamp.err.log")
    if (-not (Wait-ForService $frontendUrl 30 $frontend.Id)) {
        throw "前端未能启动。请查看 $logRoot 中的 frontend-$stamp.err.log。"
    }

    @{ Backend = (New-ProcessRecord $backend); Frontend = (New-ProcessRecord $frontend) } |
        ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
    Write-Host "平台已启动：$frontendUrl"
    Write-Host "日志目录：$logRoot"
    Start-Process $frontendUrl
} catch {
    if ($null -ne $frontend) { Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue }
    if ($null -ne $backend) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
    throw
}
