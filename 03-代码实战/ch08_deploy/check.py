"""第 08 章 L2 代码闸门：7 条断言（含真起服务做冒烟与压测）

运行：python ch08_deploy/check.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "ch07_service"))
sys.path.insert(0, HERE)

import app as svc  # noqa: E402
from loadtest import loadtest, unit_economics  # noqa: E402
from smoke_test import run_checks  # noqa: E402

DEPLOY_DIR = os.path.join(os.path.dirname(ROOT), "05-FDE部署")
RESULTS: list[tuple[str, bool, str]] = []


def check(name, fn):
    try:
        ok, msg = fn()
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"{type(e).__name__}: {e}"
    RESULTS.append((name, ok, msg))


def read(name: str) -> str:
    with open(os.path.join(DEPLOY_DIR, name), encoding="utf-8") as f:
        return f.read()


def h1_dockerfile():
    t = read("Dockerfile")
    ok = "HEALTHCHECK" in t and "USER app" in t and "EXPOSE 8080" in t and "APP_TOKEN" in t
    return ok, f"healthcheck={'HEALTHCHECK' in t} nonroot={'USER app' in t}"


def h2_compose():
    t = read("docker-compose.yml")
    ok = (
        t.count("healthcheck:") >= 2
        and "restart: unless-stopped" in t
        and "condition: service_healthy" in t
        and "max-size" in t
    )
    return ok, f"healthchecks={t.count('healthcheck:')} restart={'restart: unless-stopped' in t}"


def h3_nginx():
    t = read("nginx.conf")
    ok = "location = /healthz" in t and "try_files" in t and "X-Content-Type-Options" in t
    return ok, f"healthz={'location = /healthz' in t} hardening={'X-Content-Type-Options' in t}"


def h4_smoke():
    base = f"http://127.0.0.1:{PORT}"
    svc.STATE.windows.clear()
    res = run_checks(base, svc.DEFAULT_TOKEN)
    ok = all(r[1] for r in res)
    return ok, " | ".join(f"{n}:{'PASS' if o else 'FAIL'}" for n, o, _ in res)


def h5_loadtest():
    svc.STATE.windows.clear()
    old = svc.RL_LIMIT
    svc.RL_LIMIT = 100   # 压测放开限流，专测性能
    try:
        res = loadtest(f"http://127.0.0.1:{PORT}", svc.DEFAULT_TOKEN, concurrency=2, total=8)
    finally:
        svc.RL_LIMIT = old
    ok = res["ok"] + res["errors"] == 8 and res["p95_ms"] > 0 and res["p50_ms"] > 0
    return ok, json.dumps({k: res[k] for k in ("ok", "errors", "p50_ms", "p95_ms")}, ensure_ascii=False)


def h6_cost_model():
    econ = unit_economics(200, 900, 220, 0.002, 0.008)
    per_query_manual = round(900 / 1000 * 0.002 + 220 / 1000 * 0.008, 6)
    month_manual = round(per_query_manual * 200 * 22 + 800 + 8000, 2)
    benefit_manual = round(200 * 22 * 5 / 60 * 60, 2)
    roi_manual = round((benefit_manual - month_manual) / month_manual, 4)
    ok = (
        abs(econ["per_query_yuan"] - per_query_manual) < 1e-9
        and abs(econ["total_month_yuan"] - month_manual) < 0.02
        and abs(econ["roi"] - roi_manual) < 1e-4
    )
    return ok, f"per_query={econ['per_query_yuan']}(手算 {per_query_manual}) roi={econ['roi']}(手算 {roi_manual})"


PS_FILES = ["deploy.ps1", "stop.ps1", "rollback.ps1", "healthcheck.ps1"]


def _ps_parse_ok(path: str) -> tuple[bool, str]:
    cmd = f"[void][scriptblock]::Create((Get-Content -Raw -LiteralPath '{path}')); 'parse-ok'"
    try:
        p = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=20)
        return ("parse-ok" in p.stdout), (p.stderr.strip()[:80] or "parsed")
    except Exception:  # noqa: BLE001
        # 容器（alpine）里通常没有 pwsh：退化为静态结构检查，并如实标注
        try:
            with open(path, encoding="utf-8-sig") as f:
                src = f.read()
        except Exception as e:  # noqa: BLE001
            return False, f"读不到脚本: {e}"
        balanced = src.count("{") == src.count("}") and src.count("(") == src.count(")")
        keys = all(k in src for k in ("param(", "docker", "IMAGE_TAG"))
        ok = balanced and keys
        return ok, "static-only(pwsh 不可用)" if ok else "static-check failed"


def h7_rollback():
    t = read("rollback.ps1")
    has_model = "MODEL_VERSION" in t and "IMAGE_TAG" in t and "DryRun" in t
    parse_ok, msg = _ps_parse_ok(os.path.join(DEPLOY_DIR, "rollback.ps1"))
    return (has_model and parse_ok), f"model_version_in_rollback={has_model} syntax={msg}"


PORT = 0


def main() -> int:
    global PORT
    srv = svc.make_server(0)
    PORT = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.2)

    try:
        for name, fn in [
            ("H1 Dockerfile 合规", h1_dockerfile),
            ("H2 compose 编排", h2_compose),
            ("H3 nginx 配置", h3_nginx),
            ("H4 部署冒烟", h4_smoke),
            ("H5 压测出 P95", h5_loadtest),
            ("H6 单位经济可复算", h6_cost_model),
            ("H7 回滚脚本可解析", h7_rollback),
        ]:
            check(name, fn)
    finally:
        srv.shutdown()

    passed = 0
    for name, ok, msg in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  |  {msg}")
        passed += ok
    print(f"[CH08] {'PASS' if passed == len(RESULTS) else 'FAIL'} {passed}/{len(RESULTS)}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
