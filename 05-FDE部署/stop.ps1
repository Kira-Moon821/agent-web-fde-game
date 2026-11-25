# 停止并清理容器（不删镜像，便于快速重启）
$compose = Join-Path $PSScriptRoot "docker-compose.yml"
docker compose -f $compose down --remove-orphans
Write-Host "已停止 medai-learning 全部服务"
