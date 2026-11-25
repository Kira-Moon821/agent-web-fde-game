# FDE 一键部署（Windows / PowerShell）
# 用法：.\deploy.ps1 -Tag v1 -Token dev-token
param(
    [string]$Tag = "v1",
    [string]$Token = "dev-token",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$compose = Join-Path $PSScriptRoot "docker-compose.yml"
$siteUrl = "http://127.0.0.1:8081"
$apiUrl  = "http://127.0.0.1:8080"

Write-Host "== [1/5] 环境检查 ==" -ForegroundColor Cyan

$daemonOk = $false
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { $daemonOk = $true }
}

if (-not $daemonOk) {
    Write-Warning "Docker 守护进程不可用，改用本地 Python 直跑（站点 8081 + API 8080）。"
    $root = Split-Path -Parent $PSScriptRoot
    $siteDir = Join-Path $root "04-学习网站"
    $apiApp  = Join-Path $root "03-代码实战\ch07_service\app.py"
    $env:APP_TOKEN = $Token
    Start-Process python -ArgumentList $apiApp, "8080" -WindowStyle Hidden
    Start-Process python -ArgumentList "-m", "http.server", "8081", "--directory", $siteDir -WindowStyle Hidden
    Start-Sleep -Seconds 3
    $okLocal = $false
    for ($j = 1; $j -le 20; $j++) {
        try {
            $r1 = Invoke-WebRequest -Uri "$siteUrl/" -TimeoutSec 2 -UseBasicParsing
            $r2 = Invoke-WebRequest -Uri "$apiUrl/healthz" -TimeoutSec 2 -UseBasicParsing
            if ($r1.StatusCode -eq 200 -and $r2.StatusCode -eq 200) { $okLocal = $true; break }
        } catch { Start-Sleep -Seconds 2 }
    }
    if (-not $okLocal) { Write-Host "本地降级路径启动失败" -ForegroundColor Red; exit 1 }
    Write-Host "站点：$siteUrl   API：$apiUrl" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process $siteUrl }
    exit 0
}

$ver = (docker compose version) 2>&1
Write-Host "docker compose: $ver"

Write-Host "== [2/5] 构建镜像（tag=$Tag）==" -ForegroundColor Cyan
$env:IMAGE_TAG = $Tag
$env:APP_TOKEN = $Token
# 不加 --pull：现场内网/离线环境应复用本地基础镜像
docker compose -f $compose build
if ($LASTEXITCODE -ne 0) {
    Write-Host "构建失败。常见原因：镜像加速器不可用（检查 Docker Desktop 的 registry-mirrors）。" -ForegroundColor Red
    exit 1
}

Write-Host "== [3/5] 启动服务 ==" -ForegroundColor Cyan
docker compose -f $compose up -d --remove-orphans
if ($LASTEXITCODE -ne 0) {
    Write-Host "启动失败，输出最近日志：" -ForegroundColor Red
    docker compose -f $compose logs --tail 30
    exit 1
}

Write-Host "== [4/5] 等待健康检查 ==" -ForegroundColor Cyan
$ok = $false
for ($i = 1; $i -le 40; $i++) {
    try {
        $r1 = Invoke-WebRequest -Uri "$siteUrl/healthz" -TimeoutSec 2 -UseBasicParsing
        $r2 = Invoke-WebRequest -Uri "$apiUrl/healthz" -TimeoutSec 2 -UseBasicParsing
        if ($r1.StatusCode -eq 200 -and $r2.StatusCode -eq 200) { $ok = $true; break }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $ok) {
    Write-Host "健康检查失败，输出最近日志：" -ForegroundColor Red
    docker compose -f $compose logs --tail 50
    exit 1
}

Write-Host "== [5/5] 部署完成 ==" -ForegroundColor Green
Write-Host "站点：$siteUrl"
Write-Host "API ：$apiUrl  (Bearer $Token)"
Write-Host "指标：$apiUrl/metrics"
if (-not $NoBrowser) { Start-Process $siteUrl }
