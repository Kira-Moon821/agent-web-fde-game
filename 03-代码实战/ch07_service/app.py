"""第 07 章 · AI 服务层（标准库实现，零第三方依赖）

契约：
  POST /api/chat   Authorization: Bearer <token>  Idempotency-Key: <uuid>
  GET  /healthz
  GET  /metrics
  GET  /api/gates           章节闸门结果（只读，供学习站点展示）
  POST /api/gates/refresh   重跑 8 章闸门（需 Bearer 令牌）

覆盖：SSE 流式 / Bearer 鉴权 / 令牌窗口限流 / 幂等 / 结构化错误码 / 健康检查 / 指标 / 闸门结果
运行：python ch07_service/app.py 8080
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from mock_llm import CostLedger, MockLLM, cost_of, estimate_tokens  # noqa: E402

DEFAULT_TOKEN = os.environ.get("APP_TOKEN", "dev-token")
RL_LIMIT = int(os.environ.get("RL_LIMIT", "3"))   # 每窗口允许请求数，<=0 表示不限流（仅压测用）
RL_WINDOW_S = int(os.environ.get("RL_WINDOW_S", "60"))
MAX_INPUT_CHARS = 800

# 闸门报告：由 `run_all_checks.py --json` 生成，站点经 nginx /api 反代读取
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GATES_PATH = os.environ.get("GATES_PATH", os.path.join(PROJECT_ROOT, "03-代码实战", "reports", "gates.json"))
CHECK_RUNNER = os.path.join(PROJECT_ROOT, "03-代码实战", "run_all_checks.py")

ERRORS = {
    "AUTH_FAILED": (401, "缺少或无效的访问令牌"),
    "RATE_LIMITED": (429, "请求过于频繁"),
    "BAD_INPUT": (400, "请求体不合法"),
    "CONTEXT_OVERFLOW": (400, "输入超过上下文上限"),
    "MODEL_TIMEOUT": (504, "模型超时"),
    "NOT_FOUND": (404, "接口不存在"),
}


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.ledger = CostLedger()
        self.windows: dict[str, list[float]] = {}
        self.idempotent: dict[str, dict] = {}
        self.latencies: list[int] = []
        self.errors = 0
        self.requests = 0
        self.mock = MockLLM(slow_seconds=0.0)
        self.started = time.time()
        self.refresh_lock = threading.Lock()   # 同一时刻只允许一次闸门重跑

    def allow(self, token: str) -> tuple[bool, int]:
        if RL_LIMIT <= 0:      # 压测模式：完全放开限流
            return True, 0
        now = time.time()
        with self.lock:
            win = [t for t in self.windows.get(token, []) if now - t < RL_WINDOW_S]
            if len(win) >= RL_LIMIT:
                retry = int(RL_WINDOW_S - (now - win[0])) + 1
                self.windows[token] = win
                return False, retry
            win.append(now)
            self.windows[token] = win
            return True, 0


STATE = State()


def read_gates() -> dict | None:
    """读闸门报告；文件缺失或损坏都返回 None，由调用方决定降级文案。"""
    try:
        with open(GATES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def run_gates() -> dict:
    """同步重跑 8 章闸门并落盘。单机演示够用；生产应改为异步任务。"""
    t0 = time.time()
    p = subprocess.run(
        [sys.executable, CHECK_RUNNER, "--json", GATES_PATH, "--quiet"],
        capture_output=True, text=True, timeout=300, cwd=PROJECT_ROOT,
    )
    data = read_gates() or {"generated_at": None, "passed": 0, "total": 0, "chapters": []}
    data["runner_exit"] = p.returncode
    data["runner_seconds"] = round(time.time() - t0, 2)
    if p.returncode != 0 and not data["chapters"]:
        data["stderr"] = (p.stderr or "").strip()[:400]
    return data


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MedAI/0.1"

    # ---------- 工具 ----------
    def _json(self, code: int, payload: dict, extra_headers: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code_name: str, extra: dict | None = None, headers: dict | None = None) -> None:
        status, msg = ERRORS[code_name]
        STATE.errors += 1
        self._json(status, {"error": {"code": code_name, "message": msg, **(extra or {})}}, headers)

    def _auth(self) -> str | None:
        h = self.headers.get("Authorization", "")
        if not h.startswith("Bearer "):
            return None
        tok = h[7:].strip()
        return tok if tok == DEFAULT_TOKEN else None

    def log_message(self, fmt: str, *args) -> None:  # 静音默认日志
        return

    # ---------- GET ----------
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            self._json(200, {"status": "ok", "model": "mock-llm-1", "uptime_s": int(time.time() - STATE.started)})
            return
        if path == "/metrics":
            with STATE.lock:
                lat = sorted(STATE.latencies)
                if lat:
                    idx = min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))
                    p95 = lat[idx]
                    p50 = lat[len(lat) // 2]
                else:
                    p95 = p50 = 0
                self._json(
                    200,
                    {
                        "requests": STATE.requests,
                        "errors": STATE.errors,
                        "p50_ms": lat[len(lat) // 2] if lat else 0,
                        "p95_ms": p95,
                        "ledger": STATE.ledger.report(),
                        "idempotent_hits": len(STATE.idempotent),
                    },
                )
            return
        if path == "/api/gates":
            data = read_gates()
            if not data:
                self._json(200, {
                    "status": "missing",
                    "chapters": [],
                    "hint": "运行 python 03-代码实战/run_all_checks.py --json 03-代码实战/reports/gates.json 生成报告",
                })
            else:
                data["status"] = "ready"
                self._json(200, data)
            return
        self._error("NOT_FOUND")

    # ---------- POST ----------
    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/gates/refresh":
            token = self._auth()
            if not token:
                self._error("AUTH_FAILED")
                return
            if not STATE.refresh_lock.acquire(blocking=False):
                self._error("RATE_LIMITED", {"reason": "check_running"}, {"Retry-After": 5})
                return
            try:
                self._json(200, run_gates())
            except subprocess.TimeoutExpired:
                self._error("MODEL_TIMEOUT", {"scope": "gates"})
            except Exception as e:  # 跑崩了也要给前端一个结构化错误
                self._json(500, {"error": {"code": "CHECK_FAILED", "message": str(e)[:200]}})
            finally:
                STATE.refresh_lock.release()
            return
        if path != "/api/chat":
            self._error("NOT_FOUND")
            return

        STATE.requests += 1

        token = self._auth()
        if not token:
            self._error("AUTH_FAILED")
            return

        ok, retry = STATE.allow(token)
        if not ok:
            self._error("RATE_LIMITED", {"retry_after": retry}, {"Retry-After": retry})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            self._error("BAD_INPUT")
            return

        message = str(body.get("message", "")).strip()
        if not message:
            self._error("BAD_INPUT", {"field": "message"})
            return
        if len(message) > MAX_INPUT_CHARS:
            self._error("CONTEXT_OVERFLOW", {"max_chars": MAX_INPUT_CHARS, "actual": len(message)})
            return

        idem = self.headers.get("Idempotency-Key", "")
        if idem:
            with STATE.lock:
                if idem in STATE.idempotent:
                    cached = STATE.idempotent[idem]
                    self._json(200, cached, {"Idempotent-Replay": "1"})
                    return

        t0 = time.time()
        prompt = f"system: 你是医疗知识库助手，只基于资料回答。\nuser: {message}"
        answer = (
            "结论：该指标需结合临床表现综合判断。依据：见 doc1#p1。"
            "免责：本内容不替代医生诊断。"
        )
        citations = ["doc1#p1"]
        pt, ct = estimate_tokens(prompt), estimate_tokens(answer)
        cost = cost_of(pt, ct)
        with STATE.lock:
            STATE.ledger.calls += 1
            STATE.ledger.prompt_tokens += pt
            STATE.ledger.completion_tokens += ct
            STATE.ledger.cost = round(STATE.ledger.cost + cost, 6)

        stream = bool(body.get("stream", True))

        if not stream:
            payload = {"answer": answer, "citations": citations, "cost": {"prompt_tokens": pt, "completion_tokens": ct, "yuan": cost}}
            if idem:
                with STATE.lock:
                    STATE.idempotent[idem] = payload
            self._json(200, payload)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        seq = 0
        for chunk in STATE.mock.stream(answer, chunk=10):
            seq += 1
            data = json.dumps({"seq": seq, "delta": chunk}, ensure_ascii=False)
            self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.005)
        done = {"done": True, "seq": seq, "citations": citations, "cost": {"prompt_tokens": pt, "completion_tokens": ct, "yuan": cost}, "latency_ms": int((time.time() - t0) * 1000)}
        self.wfile.write(f"data: {json.dumps(done, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()

        with STATE.lock:
            STATE.latencies.append(done["latency_ms"])
            if idem:
                STATE.idempotent[idem] = {"answer": answer, "citations": citations, "cost": done["cost"]}
        self.close_connection = True


def make_server(port: int = 0, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    return srv


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    # 容器/内网部署必须监听 0.0.0.0，否则端口映射只能打到容器内的 127.0.0.1
    host = os.environ.get("APP_HOST", "0.0.0.0")
    srv = make_server(port, host)
    print(f"服务已启动：http://{host}:{port}  token={DEFAULT_TOKEN}  (Ctrl+C 停止)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        srv.shutdown()


if __name__ == "__main__":
    main()
