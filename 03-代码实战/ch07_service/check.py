"""第 07 章 L2 代码闸门：8 条断言（真起服务、真打接口）

运行：python ch07_service/check.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)

import app as svc  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []
BASE = ""


def check(name, fn):
    try:
        ok, msg = fn()
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"{type(e).__name__}: {e}"
    RESULTS.append((name, ok, msg))


def req(path: str, method: str = "GET", payload: dict | None = None, headers: dict | None = None) -> tuple[int, dict, bytes]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers or {})
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


AUTH = {"Authorization": f"Bearer {svc.DEFAULT_TOKEN}"}


def g1_health():
    code, _, body = req("/healthz")
    j = json.loads(body)
    return code == 200 and j["status"] == "ok", f"code={code} body={j}"


def g2_auth():
    code, _, body = req("/api/chat", "POST", {"message": "你好", "stream": False})
    j = json.loads(body)
    return code == 401 and j["error"]["code"] == "AUTH_FAILED", f"code={code} err={j.get('error')}"


def g3_normal():
    code, _, body = req("/api/chat", "POST", {"message": "ALT 参考区间？", "stream": False}, AUTH)
    j = json.loads(body)
    ok = code == 200 and "answer" in j and j["citations"] and "cost" in j
    return ok, f"code={code} cites={j.get('citations')} cost={j.get('cost', {}).get('yuan')}"


def g4_sse():
    code, hdrs, body = req("/api/chat", "POST", {"message": "解释 ALT", "stream": True}, AUTH)
    lines = [l[6:] for l in body.decode("utf-8").splitlines() if l.startswith("data: ")]
    events = [json.loads(l) for l in lines if l.strip()]
    deltas = [e["delta"] for e in events if "delta" in e]
    done = [e for e in events if e.get("done")]
    ok = code == 200 and "text/event-stream" in hdrs.get("Content-Type", "") and deltas and done and "".join(deltas) == done[0].get("answer", "".join(deltas))
    return ok, f"code={code} chunks={len(deltas)} done={bool(done)}"


def g5_idempotent():
    calls_before = svc.STATE.ledger.calls
    key = {"Idempotency-Key": "test-key-001", **AUTH}
    c1, h1, b1 = req("/api/chat", "POST", {"message": "同一请求", "stream": False}, key)
    calls_after_first = svc.STATE.ledger.calls
    c2, h2, b2 = req("/api/chat", "POST", {"message": "同一请求", "stream": False}, key)
    calls_after_second = svc.STATE.ledger.calls
    ok = (
        c1 == c2 == 200
        and calls_after_first == calls_before + 1
        and calls_after_second == calls_after_first
        and h2.get("Idempotent-Replay", h2.get("idempotent-replay")) == "1"
    )
    return ok, f"calls {calls_before}→{calls_after_first}→{calls_after_second} replay={h2.get('Idempotent-Replay', h2.get('idempotent-replay'))}"


def g6_context_overflow():
    code, _, body = req("/api/chat", "POST", {"message": "长" * 1000, "stream": False}, AUTH)
    j = json.loads(body)
    return code == 400 and j["error"]["code"] == "CONTEXT_OVERFLOW", f"code={code} err={j.get('error')}"


def g7_rate_limit():
    svc.STATE.windows.clear()
    codes = []
    retry_after = None
    for i in range(svc.RL_LIMIT + 1):
        c, h, b = req("/api/chat", "POST", {"message": f"限流测试{i}", "stream": False}, AUTH)
        codes.append(c)
        if c == 429:
            retry_after = h.get("Retry-After")
            j = json.loads(b)
    ok = codes[:-1] == [200] * svc.RL_LIMIT and codes[-1] == 429 and retry_after is not None
    return ok, f"codes={codes} retry_after={retry_after}"


def g8_metrics():
    code, _, body = req("/metrics")
    j = json.loads(body)
    ok = code == 200 and j["requests"] > 0 and j["errors"] > 0 and "p95_ms" in j and j["ledger"]["calls"] > 0
    return ok, f"requests={j.get('requests')} errors={j.get('errors')} p95={j.get('p95_ms')} calls={j.get('ledger', {}).get('calls')}"


def main() -> int:
    global BASE
    srv = svc.make_server(0)
    port = srv.server_address[1]
    BASE = f"http://127.0.0.1:{port}"
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    time.sleep(0.2)

    try:
        for name, fn in [
            ("G1 健康检查", g1_health),
            ("G2 无令牌401", g2_auth),
            ("G3 普通问答", g3_normal),
            ("G4 SSE流式", g4_sse),
            ("G5 幂等不重复计费", g5_idempotent),
            ("G6 上下文超限", g6_context_overflow),
            ("G7 限流429+Retry-After", g7_rate_limit),
            ("G8 指标端点", g8_metrics),
        ]:
            svc.STATE.windows.clear()   # 每个用例独立窗口，避免相互干扰
            check(name, fn)
    finally:
        srv.shutdown()

    passed = 0
    for name, ok, msg in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  |  {msg}")
        passed += ok
    print(f"[CH07] {'PASS' if passed == len(RESULTS) else 'FAIL'} {passed}/{len(RESULTS)}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
