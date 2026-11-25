import json
import time
import urllib.error
import urllib.request

log = []


def say(s):
    log.append(s)


try:
    r = urllib.request.urlopen("http://127.0.0.1:8081/api/gates", timeout=5)
    d = json.load(r)
    say(f"GET /api/gates -> {r.status} status={d.get('status')} {d.get('passed')}/{d.get('total')} chapters={len(d.get('chapters', []))}")
except Exception as e:
    say(f"GET FAIL {e}")

try:
    req = urllib.request.Request(
        "http://127.0.0.1:8081/api/gates/refresh", method="POST",
        headers={"Authorization": "Bearer dev-token"},
    )
    t = time.time()
    r = urllib.request.urlopen(req, timeout=300)
    d = json.load(r)
    say(f"REFRESH -> {r.status} {d['passed']}/{d['total']} runner={d.get('runner_seconds')}s wall={time.time()-t:.1f}s")
except Exception as e:
    say(f"REFRESH FAIL {e}")

try:
    req = urllib.request.Request("http://127.0.0.1:8081/api/gates/refresh", method="POST")
    urllib.request.urlopen(req, timeout=5)
    say("NOAUTH -> 竟然成功了（异常）")
except urllib.error.HTTPError as e:
    say(f"NOAUTH -> {e.code} {e.read()[:80].decode('utf-8', 'ignore')}")
except Exception as e:
    say(f"NOAUTH FAIL {e}")

open(r"F:\doubao\project1-ai医疗大模型行业分析\03-代码实战\reports\_api_smoke.txt", "w", encoding="utf-8").write("\n".join(log))
print("\n".join(log))
