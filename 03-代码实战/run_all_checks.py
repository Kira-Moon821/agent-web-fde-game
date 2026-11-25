"""一次跑完 1–8 章闸门

运行：
    python 03-代码实战/run_all_checks.py
    python 03-代码实战/run_all_checks.py --json 03-代码实战/reports/gates.json

--json 会把结果写成站点/API 可读的闸门报告（`GET /api/gates` 读的就是它）。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = [
    ("CH01", "ch01_api_baseline/check.py", "ch01"),
    ("CH02", "ch02_prompt_harness/check.py", "ch02"),
    ("CH03", "ch03_rag/check.py", "ch03"),
    ("CH04", "ch04_agent_tools/check.py", "ch04"),
    ("CH05", "ch05_finetune_data/check.py", "ch05"),
    ("CH06", "ch06_eval/check.py", "ch06"),
    ("CH07", "ch07_service/check.py", "ch07"),
    ("CH08", "ch08_deploy/check.py", "ch08"),
]


def parse_counts(tail: str) -> tuple[int, int]:
    """从 `[CH01] PASS 6/6` 里取出通过数与总数。"""
    m = re.search(r"\b(\d+)/(\d+)\b", tail or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def run_all() -> tuple[list[dict], float]:
    rows: list[dict] = []
    t_all = time.time()
    for tag, rel, cid in CHECKS:
        t0 = time.time()
        p = subprocess.run([sys.executable, os.path.join(HERE, rel)], capture_output=True, text=True, timeout=180)
        tail = ""
        for line in (p.stdout or "").splitlines():
            if line.startswith(f"[{tag}]"):
                tail = line
        passed_n, total_n = parse_counts(tail)
        rows.append({
            "id": cid,
            "label": tag,
            "status": "PASS" if p.returncode == 0 else "FAIL",
            "passed": passed_n,
            "total": total_n,
            "summary": tail or (p.stderr or "").strip()[:120],
            "duration_s": round(time.time() - t0, 2),
        })
    return rows, round(time.time() - t_all, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_path", default="", help="把报告写到指定 JSON 路径")
    ap.add_argument("--quiet", action="store_true", help="只写 JSON，不打印表格")
    args = ap.parse_args()

    rows, total_dur = run_all()
    passed = sum(1 for r in rows if r["status"] == "PASS")

    if not args.quiet:
        print("=" * 64)
        print(f"{'章':6s} {'结果':6s} {'摘要':40s} {'耗时':>6s}")
        print("-" * 64)
        for r in rows:
            print(f"{r['label']:6s} {r['status']:6s} {r['summary'][:40]:40s} {r['duration_s']:5.1f}s")
        print("=" * 64)
        print(f"合计 {passed}/{len(rows)} 通过，总耗时 {total_dur:.1f}s")

    if args.json_path:
        report = {
            # 统一用 UTC（带 Z），由前端转成本地时间显示，避免容器时区差异
            "generated_at": datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "duration_s": total_dur,
            "passed": passed,
            "total": len(rows),
            "chapters": rows,
        }
        path = args.json_path
        if not os.path.isabs(path):
            # 相对路径按项目根解析，便于 --json 03-代码实战/reports/gates.json
            path = os.path.join(os.path.dirname(HERE), path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        if not args.quiet:
            print(f"报告已写入：{path}")

    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
