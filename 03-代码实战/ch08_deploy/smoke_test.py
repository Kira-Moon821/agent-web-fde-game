"""第 08 章 · 部署后冒烟测试（真打接口）

运行：python ch08_deploy/smoke_test.py --base http://127.0.0.1:8080 --token dev-token
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def _req(base: str, path: str, method: str = "GET", payload: dict | None = None, headers: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    r = urllib.request.Request(base + path, data=data, method=method, headers=headers or {})
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def run_checks(base: str, token: str) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    auth = {"Authorization": f"Bearer {token}"}

    c, _, b = _req(base, "/healthz")
    out.append(("健康检查", c == 200 and json.loads(b).get("status") == "ok", f"HTTP {c}"))

    c, _, b = _req(base, "/api/chat", "POST", {"message": "冒烟测试"})
    out.append(("鉴权拦截", c == 401, f"HTTP {c}"))

    c, _, b = _req(base, "/api/chat", "POST", {"message": "ALT 参考区间", "stream": False}, auth)
    j = json.loads(b) if c == 200 else {}
    out.append(("问答可用", c == 200 and bool(j.get("answer")) and bool(j.get("citations")), f"HTTP {c}"))

    c, hdrs, b = _req(base, "/api/chat", "POST", {"message": "流式冒烟", "stream": True}, auth)
    text = b.decode("utf-8", "ignore")
    out.append(("流式返回", c == 200 and "data:" in text and '"done": true' in text, f"HTTP {c} bytes={len(b)}"))

    c, _, b = _req(base, "/metrics")
    j = json.loads(b) if c == 200 else {}
    out.append(("指标可用", c == 200 and "ledger" in j, f"HTTP {c}"))

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--token", default="dev-token")
    args = ap.parse_args()

    res = run_checks(args.base, args.token)
    passed = 0
    for name, ok, msg in res:
        print(f"{'PASS' if ok else 'FAIL'}  {name:8s} | {msg}")
        passed += ok
    print(f"[SMOKE] {'PASS' if passed == len(res) else 'FAIL'} {passed}/{len(res)}")
    return 0 if passed == len(res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
