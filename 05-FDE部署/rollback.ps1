# 回滚：切回上一个镜像 tag，并把模型版本一起回退（模型回滚最容易被忘）
# 用法：.\rollback.ps1 -PreviousTag v1 -PreviousModel mock-llm-0
param(
    [string]$PreviousTag = "v1",
    [string]$PreviousModel = "mock-llm-1",
    [switch]$DryRun
)

$compose = Join-Path $PSScriptRoot "docker-compose.yml"

if ($DryRun) {
    Write-Host "[dry-run] 将执行：IMAGE_TAG=$PreviousTag MODEL_VERSION=$PreviousModel docker compose -f $compose up -d --force-recreate"
    Write-Host "[dry-run] 随后校验 http://127.0.0.1:8081/healthz 与 http://127.0.0.1:8080/healthz"
    exit 0
}

$env:IMAGE_TAG = $PreviousTag
$env:MODEL_VERSION = $PreviousModel
docker compose -f $compose up -d --force-recreate

Start-Sleep -Seconds 5
try {
    $r1 = Invoke-WebRequest -Uri "http://127.0.0.1:8081/healthz" -TimeoutSec 3 -UseBasicParsing
    $r2 = Invoke-WebRequest -Uri "http://127.0.0.1:8080/healthz" -TimeoutSec 3 -UseBasicParsing
    if ($r1.StatusCode -eq 200 -and $r2.StatusCode -eq 200) {
        Write-Host "回滚成功：IMAGE_TAG=$PreviousTag, MODEL_VERSION=$PreviousModel" -ForegroundColor Green
        exit 0
    }
} catch {
    Write-Host "回滚后健康检查未通过：$($_.Exception.Message)" -ForegroundColor Red
}
exit 1
