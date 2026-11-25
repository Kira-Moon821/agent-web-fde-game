# 交付前/后的健康检查（给客户 IT 用的最小验收脚本）
$targets = @(
    @{ Name = "站点"; Url = "http://127.0.0.1:8081/healthz" },
    @{ Name = "API 健康"; Url = "http://127.0.0.1:8080/healthz" },
    @{ Name = "API 指标"; Url = "http://127.0.0.1:8080/metrics" }
)

$failed = 0
foreach ($t in $targets) {
    try {
        $r = Invoke-WebRequest -Uri $t.Url -TimeoutSec 3 -UseBasicParsing
        if ($r.StatusCode -eq 200) {
            Write-Host ("[OK]   {0}  {1}" -f $t.Name, $t.Url) -ForegroundColor Green
            Write-Output ("[OK]   {0}  {1}" -f $t.Name, $t.Url)
        } else {
            Write-Host ("[FAIL] {0}  HTTP {1}" -f $t.Name, $r.StatusCode) -ForegroundColor Red
            Write-Output ("[FAIL] {0}  HTTP {1}" -f $t.Name, $r.StatusCode)
            $failed++
        }
    } catch {
        Write-Host ("[FAIL] {0}  {1}" -f $t.Name, $_.Exception.Message) -ForegroundColor Red
        Write-Output ("[FAIL] {0}  {1}" -f $t.Name, $_.Exception.Message)
        $failed++
    }
}
Write-Output ("[HEALTHCHECK] " + $(if ($failed -eq 0) { "PASS 3/3" } else { "FAIL $failed" }))
exit $failed
