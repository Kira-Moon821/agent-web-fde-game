"""第 08 章 · 轻量压测 + 单位经济成本模型

运行：python ch08_deploy/loadtest.py --base http://127.0.0.1:8080 --token dev-token --concurrency 4 --total 20
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import threading
import time
import urllib.error
import urllib.request


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
    return round(s[idx], 1)


def _one(base: str, token: str, n: int) -> tuple[int, float]:
    payload = json.dumps({"message": f"压测请求 {n}", "stream": False}).encode("utf-8")
    r = urllib.request.Request(
        base + "/api/chat",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "Idempotency-Key": f"load-{n}-{time.time_ns()}"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            resp.read()
            return resp.status, (time.time() - t0) * 1000
    except urllib.error.HTTPError as e:
        return e.code, (time.time() - t0) * 1000
    except Exception:  # 连接重置/超时也计入错误，不能让线程静默崩溃
        return 0, (time.time() - t0) * 1000


def loadtest(base: str, token: str, concurrency: int, total: int) -> dict:
    lat: list[float] = []
    codes: list[int] = []
    lock = threading.Lock()

    def worker(idx: int) -> None:
        c, ms = _one(base, token, idx)
        with lock:
            lat.append(ms)
            codes.append(c)

    threads = []
    for i in range(total):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()
        if len(threads) % concurrency == 0:
            for t in threads:
                t.join()
            threads = []
    for t in threads:
        t.join()

    return {
        "total": total,
        "ok": sum(1 for c in codes if c == 200),
        "errors": sum(1 for c in codes if c != 200),
        "error_rate": round(sum(1 for c in codes if c != 200) / max(total, 1), 4),
        "codes": {str(k): v for k, v in sorted(collections.Counter(codes).items())},
        "p50_ms": round(statistics.median(lat), 1) if lat else 0,
        "p95_ms": p95(lat),
        "qps": round(total / max(sum(lat) / 1000 / max(concurrency, 1), 1e-6), 2),
    }


# ---------------- 单位经济 ----------------
def unit_economics(
    queries_per_day: int,
    input_tokens: int,
    output_tokens: int,
    price_in_per_1k: float,
    price_out_per_1k: float,
    infra_month_yuan: float = 800,
    labor_month_yuan: float = 8000,
    saved_minutes_per_query: float = 5.0,
    staff_hourly_yuan: float = 60.0,
    workdays: int = 22,
) -> dict:
    per_query = (input_tokens / 1000 * price_in_per_1k) + (output_tokens / 1000 * price_out_per_1k)
    model_month = per_query * queries_per_day * workdays
    total_month = model_month + infra_month_yuan + labor_month_yuan
    saved_hours_month = queries_per_day * workdays * saved_minutes_per_query / 60
    benefit_month = saved_hours_month * staff_hourly_yuan
    roi = (benefit_month - total_month) / total_month
    return {
        "per_query_yuan": round(per_query, 6),
        "per_1k_queries_yuan": round(per_query * 1000, 2),
        "model_month_yuan": round(model_month, 2),
        "total_month_yuan": round(total_month, 2),
        "saved_hours_month": round(saved_hours_month, 1),
        "benefit_month_yuan": round(benefit_month, 2),
        "roi": round(roi, 4),
        "breakeven_queries_per_day": (
            round((infra_month_yuan + labor_month_yuan) / (per_query * workdays), 0) if per_query > 0 else None
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--token", default="dev-token")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--total", type=int, default=20)
    args = ap.parse_args()

    res = loadtest(args.base, args.token, args.concurrency, args.total)
    print("压测结果：", json.dumps(res, ensure_ascii=False, indent=2))

    econ = unit_economics(queries_per_day=200, input_tokens=900, output_tokens=220,
                          price_in_per_1k=0.002, price_out_per_1k=0.008)
    print("\n单位经济：", json.dumps(econ, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
