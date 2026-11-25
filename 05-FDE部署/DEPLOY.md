# FDE 交付手册：AI 医疗知识问答（单机内网版）

本目录是把「一个能演示的 AI 应用」变成「一套客户 IT 敢接、能自己运维的系统」的最小完整实现。目标读者是两类人：负责现场交付的 FDE，以及客户方接手运维的 IT。

技术栈刻意朴素：Python 标准库 HTTP 服务 + 静态站点 + Nginx，双容器编排，无数据库、无外部依赖、无外网即可运行。理由很简单——客户内网往往装不了 Kubernetes，也装不了复杂中间件；一个能在单机 Docker 上跑起来、坏了自己能看日志恢复的系统，比一个架构漂亮但没人敢碰的系统更有价值。

## 1. 目录与环境要求

| 文件 | 作用 |
|---|---|
| `Dockerfile` | API 镜像，非 root 用户运行，内置 HEALTHCHECK |
| `docker-compose.yml` | 双服务编排：`api`（8080）+ `site`（8081），双健康检查、失败重启、日志滚动 |
| `nginx.conf` | 站点配置，含 `/healthz`、安全响应头、静态资源缓存 |
| `deploy.ps1` | 一键构建并启动，失败自动退到本地进程模式 |
| `stop.ps1` | 停止并清理 |
| `rollback.ps1` | 回到上一个镜像标签 |
| `healthcheck.ps1` | 交付前/后的三点健康检查，给客户 IT 用的最小验收脚本 |
| `DEPLOY.md` | 本文件 |

环境要求：Docker 24+ 与 Compose v2；Windows 下需 Docker Desktop 已启动（不是装了就一定在跑，`deploy.ps1` 会先探测守护进程）。端口占用：8080（API）、8081（站点）。

## 2. Scope：这一版交付什么，不交付什么

**交付**

- 单轮医疗知识问答 API：`POST /api/chat`，支持 `stream: true` 的 SSE 流式返回。
- 鉴权（Bearer Token）、限流（令牌窗口）、输入长度上限、幂等键、错误码规范化。
- 指标接口 `/metrics`（请求数、错误数、P50/P95、成本台账）。
- 闸门接口：`GET /api/gates`（只读，供站点展示）、`POST /api/gates/refresh`（Bearer 鉴权，服务端重跑 8 章 check.py）。
- 静态学习站点（8 关像素地图），Nginx 托管，并通过 `/api/` 反代后端。
- 健康检查、冒烟脚本、压测脚本、回滚脚本。

**不交付（写进合同，避免后面扯皮）**

- 不做诊断、不给用药剂量建议，只做「解释 + 提示就医」。
- 不接 HIS/LIS、不做单点登录、不做多租户。
- 不做模型微调与 GPU 推理（本版用确定性 Mock 模型，接真实模型只需替换 `LLMClient` 的 provider）。
- 不做高可用集群；单机重启期间服务中断，属预期。

## 3. 部署步骤

```powershell
cd F:\doubao\project1-ai医疗大模型行业分析
pwsh -File 05-FDE部署\deploy.ps1        # 构建 + 启动 + 轮询健康检查
pwsh -File 05-FDE部署\healthcheck.ps1   # 三点验收：站点 /healthz、API /healthz、/metrics
python 03-代码实战\ch08_deploy\smoke_test.py --base http://127.0.0.1:8080 --token dev-token
```

站点 `http://127.0.0.1:8081`，API `http://127.0.0.1:8080`。环境变量：`APP_TOKEN`（访问令牌）、`MODEL_VERSION`（模型标识，写进响应头便于排查）、`RL_LIMIT`/`RL_WINDOW_S`（限流窗口）、`IMAGE_TAG`（镜像标签，回滚靠它）。

## 4. 六段闭环（D1–D6）

FDE 的价值不在"会调模型"，在于把交付拆成客户能逐段验收的动作。每段都要有交付物和验收人，否则项目会在"我觉得差不多了"里烂掉。

| 段 | 关键动作 | 交付物 | 验收人 | 本项目对应 |
|---|---|---|---|---|
| D1 Discover | 现场访谈、看真实工单、量化基线 | 一页 paper | 客户业务负责人 | `03-代码实战/ch07_service/paper.md` |
| D2 Scope | 定最小可验收范围 + 明确非目标 | Scope 表 | 客户 + 你方 PM | 本文件第 2 节 |
| D3 Pilot | 单场景 2 周跑通 | 可点开的 Demo + 首轮评测 | 一线使用者 | `deploy.ps1` + `ch06_eval` |
| D4 Harden | 鉴权、限流、审计、错误码、脱敏 | 安全清单逐项打勾 | 客户 IT | `ch07_service` + 本文件第 8 节 |
| D5 Handover | 运维手册、监控看板、回滚演练 | 移交清单 + 演练记录 | 客户运维 | 本文件 + `rollback.ps1` |
| D6 Review | 用数据对 ROI，决定扩容或止损 | 单位经济一页纸 | 客户决策层 | 本文件第 7 节 |

D3 到 D4 之间最容易出事：Demo 能跑，但一把并发上来、一换真实数据就露馅。所以第 9.3 节那条压测必须做，而且要能区分限流和故障。

## 5. 监控与告警阈值

单机部署不需要 Prometheus，但需要三个数字和三条线。

| 指标 | 来源 | 正常 | 告警阈值 | 处置 |
|---|---|---|---|---|
| 可用性 | `healthcheck.ps1` | 3/3 通过 | 连续 3 次失败 | 查容器日志，必要时 `rollback.ps1` |
| 错误率 | `/metrics` 的 `errors/requests` | < 2% | > 5% 持续 10 分钟 | 看错误码分布：429 是限流，504 是模型超时 |
| P95 延迟 | `/metrics` | < 1.5 s | > 3 s 持续 5 分钟 | 先看是否模型侧变慢，再决定降级 |
| 单次成本 | `/metrics` 的 ledger | 0.0036 元 | 超预算 1.5 倍 | 查输入长度是否被滥用 |

日志：`docker compose logs -f api`，已配 `json-file` 滚动（10 MB × 3 份），不会把磁盘写满。这台机器不需要额外的日志系统。

## 6. 回滚

三条触发线，命中任意一条就回滚，不讨论：

1. 部署后 30 分钟内错误率 > 10%。
2. 出现安全类问题（越权、提示词注入成功拿到系统指令、输出诊断性结论）。
3. 客户业务方明确反馈"比原来还慢/还难用"。

```powershell
pwsh -File 05-FDE部署\rollback.ps1 -Tag v1   # 指回上一个可用标签
```

镜像标签是回滚的唯一抓手，所以每次交付必须换标签（`IMAGE_TAG=v2`），不允许覆盖同名标签。回滚只换镜像，不动数据与配置，30 秒内可完成。

## 7. 单位经济：先算这笔账，再谈方案

用 `ch08_deploy/loadtest.py` 可复算。两个版本放在一起看，才不会被"AI 提效"这四个字骗过去。

**版本 A（乐观口径：日均 200 次，节省按 366.7 工时计）**

| 项 | 假设 | 结果 |
|---|---|---|
| 单次问答 | 输入 900 tok × 0.002 元/1K + 输出 220 tok × 0.008 元/1K | 0.00356 元 |
| 每天 200 次、每月 22 天 | — | 模型成本 15.66 元/月 |
| 基础设施 + 人力 | 800 + 8000 元/月 | 总成本 8815.66 元/月 |
| 节省工时 | 366.7 小时 × 60 元 | 22000 元/月 |
| ROI | 22000 / 8815.66 - 1 | ≈ 1.50 |
| 盈亏平衡 | — | 112,360 次/日 |

**版本 B（保守口径：每次只省 1 分钟）**

| 项 | 假设 | 结果 |
|---|---|---|
| 基础设施 + 人力 | 800 + 8000 元/月 | 总成本 8815.66 元/月 |
| 节省工时 | 每次 5 分钟、60 元/小时 | 3666.7 元/月 |
| ROI | — | ≈ -0.55（**这个场景不值**） |

> 版本 B 的负 ROI 不是 bug，是结论：**日均 200 次的问答撑不起 8000 元人力**。要么把日均调用拉到 2000+，要么把人力按 0.2 人分摊，要么承认这是"体验升级"而不是"成本节省"，用另一套指标（投诉率、患者等待时长）来验收。报方案前先算这一步，比讲十页"赋能"有用。

## 8. 客户 IT 安全评审清单

- [ ] 容器非 root 运行，根文件系统只读（本镜像已用非 root 用户）
- [ ] 密钥不落镜像、不进 compose 明文（用环境变量 / Secret）
- [ ] 出网白名单：只允许模型服务域名
- [ ] 日志脱敏：手机号 / 证件号 / 患者标识
- [ ] 数据不出域：本地部署时模型走内网网关
- [ ] 审计：谁在什么时候调用了哪个工具（`ch04` 的 audit 日志）
- [ ] 依赖最小化：镜像内无第三方 Python 包，减少漏洞面
- [ ] 升级窗口与回滚方案已书面确认

## 9. 本机实测记录（2026-11-25，Windows + Docker Desktop）

不是"应该能跑"，是"跑过、挂过、修好后重跑"的记录。现场遇到同类问题时可直接照抄处置。

### 9.1 验收证据

| 项 | 命令 | 结果 |
|---|---|---|
| 双容器状态 | `docker ps` | `medai-api` Up (healthy) 8080、`medai-site` Up (healthy) 8081 |
| 健康检查 | `healthcheck.ps1` | PASS 3/3（站点 /healthz、API /healthz、/metrics） |
| 冒烟 | `smoke_test.py` | PASS 5/5（200 / 401 鉴权 / 200 问答 / 流式 423 bytes / 200 指标） |
| 压测 | `loadtest.py --concurrency 8 --total 40` | ok 40/40，error_rate 0，P50 8.7 ms，P95 364.9 ms，QPS 129.7 |
| 章节闸门 | `run_all_checks.py` | 8/8 PASS，总耗时 8.8 s |
| 站点实机 | 浏览器打开 `http://127.0.0.1:8081` | 16:9 舞台 + 3:4 侧栏，8 关全部渲染，`04-学习网站/preview.png` 为证 |
| 闸门接口 | `gates_probe.py` | `GET /api/gates` 200 且 8/8；`POST /api/gates/refresh` 200 且 **8/8**（容器内 12.48s）；无令牌 401 |

### 9.2 故障一：容器健康但宿主机连不上（最阴的一种）

- 现象：`docker ps` 显示 API healthy（容器内 healthcheck 打 127.0.0.1 成功），但宿主机 `curl 127.0.0.1:8080/healthz` 直接连接被关闭；nginx 站点的 8081 却完全正常。
- 根因：`app.py` 的 `make_server(port)` 默认绑定 `127.0.0.1`，容器内只有 loopback 能连，Docker 端口映射打到容器 eth0 就被拒。健康检查在容器内部跑，所以永远显示 healthy——**健康检查通过不代表端口通**。
- 处置：服务默认监听 `APP_HOST`（默认 `0.0.0.0`），compose 显式声明 `APP_HOST: 0.0.0.0`。
- 教训：容器健康检查要区分「进程活着」和「端口可用」；宿主机侧必须单独跑一次 `smoke_test.py`，这一步不能省。

### 9.3 故障二：压测 40 个线程全报 RemoteDisconnected

- 现象：`loadtest.py` 20~40 并发时全部 `http.client.RemoteDisconnected`，统计输出 ok=0 / errors=0，看起来像网络问题。
- 根因有两层：
  1. `RL_LIMIT=0`（压测放开限流）时，代码仍执行 `len(win) >= RL_LIMIT`，空窗口命中分支后取 `win[0]` → `IndexError`，handler 抛异常直接断连，客户端只看到连接被关。
  2. 压测线程没有兜底，异常在线程里抛出，统计里既不计 ok 也不计 error，于是出现"0/0"的假数据。
- 处置：`allow()` 在 `RL_LIMIT <= 0` 时直接放行；`loadtest._one()` 捕获所有异常并归入错误码 `0`；输出增加 `codes` 分布，一眼能看出是 429 限流还是连接故障。
- 教训：**压测统计必须能区分"没打到"和"打到了但被拒"**。ok=0 且 errors=0 是典型的统计失效，不是零故障。

### 9.4 故障三：镜像拉不下来

- 现象：`python:3.13-alpine` / `nginx:alpine` pull 全部失败。
- 根因：Docker Desktop 配置的 `docker.mirrors.ustc.edu.cn` 已 DNS 失效。
- 处置：改用 `docker.m.daocloud.io` 拉取后 `docker tag` 成官方名；`deploy.ps1` 已把 `--pull` 去掉，并加「镜像加速器不可用」提示。
- 离线交付建议：`docker save -o medai-images.tar medai-api:v1 nginx:alpine`，现场 `docker load -i medai-images.tar`，完全不依赖外网。

### 9.5 限流与压测的正确关系

生产保持 `RL_LIMIT=60/分钟`（compose 默认），压测时临时 `RL_LIMIT=0` 单独起一次，测完立刻恢复：

```powershell
$env:RL_LIMIT="0"; docker compose -f 05-FDE部署/docker-compose.yml up -d --force-recreate api
python 03-代码实战/ch08_deploy/loadtest.py --concurrency 8 --total 40
Remove-Item Env:RL_LIMIT
docker compose -f 05-FDE部署/docker-compose.yml up -d --force-recreate api   # 恢复限流
```

把容量数据和限流数据混在一起测，得到的 P95 是假的：429 响应只有几毫秒，会把延迟分布拉得很好看。

### 9.6 站点接入 API 时踩的四个坑（A 模式新增）

这一轮把「页面上的检验」接到服务端真实闸门，暴露的问题都值得记：

1. **镜像里没有部署文件 → CH08 容器内 3/7**。原来 Dockerfile 只 COPY 了 `03-代码实战`，而第 8 章 check.py 要读 `05-FDE部署/Dockerfile`、`docker-compose.yml`、`nginx.conf`、`rollback.ps1`。CI 里表现为"刷新闸门后 7/8"。
   - 处置：`COPY 05-FDE部署/ ./05-FDE部署/`。**如果闸门要在容器内自证，被检查的部署文件就必须进镜像**，否则闸门只能永远在宿主机跑。
2. **容器内没有 pwsh → H7 失败**。`rollback.ps1` 的语法校验依赖 `pwsh`，alpine 镜像里没有。
   - 处置：`_ps_parse_ok()` 降级为静态结构检查（括号配平 + 关键指令存在），输出里明确标 `static-only(pwsh 不可用)`。**降级必须写在结果里**，否则等于悄悄降低验收标准。
3. **接口 200 但页面没变 → 浏览器缓存旧 JS**。Nginx 对 js/css 设了 7 天缓存，改了 `app.js` 却仍加载旧版本，`fetch('/api/gates')` 手动能通、页面 `闸门` 一直显示"连接中…"。
   - 处置：入口页 `Cache-Control: no-store`，资源引用加 `?v=1.2`。判断方法：在控制台跑一次 `fetch('/api/gates')`，能通说明后端没事，问题在前端缓存。
4. **容器时钟与宿主机差 8 小时**。报告里的 `generated_at` 不可直接展示。
   - 处置：页面只显示「读取于 <浏览器本地时间>」，耗时证据用 `duration_s`。**凡是跨环境的时间戳，都不要当成 SLA 证据。**

> 这一节的共同点：三个问题都不是"代码写错"，而是"环境假设没写进代码"。FDE 现场最常见的就是这类，验收时只看日志和数字，不看"我觉得应该没问题"。

## 10. 移交清单（D5 用，逐项签字）

| # | 项 | 交付形式 | 是否完成 |
|---|---|---|---|
| 1 | 部署包（镜像 + compose + nginx 配置） | 目录 / tar 包 | 是 |
| 2 | 一键部署与停止脚本 | `deploy.ps1` / `stop.ps1` | 是 |
| 3 | 健康检查脚本与预期输出 | `healthcheck.ps1` + 本文 9.1 | 是 |
| 4 | 回滚脚本与演练记录 | `rollback.ps1` + 本文第 6 节 | 是 |
| 5 | 环境变量与密钥说明 | 本文第 3 节 | 是 |
| 6 | 监控指标含义与阈值 | 本文第 5 节 | 是 |
| 7 | 故障处置手册（含三个真实案例） | 本文第 9 节 | 是 |
| 8 | 评测报告与金标集 | `ch06_eval/reports/` | 是 |
| 9 | 业务基线一页纸 | `ch07_service/paper.md` | 是 |
| 10 | 运维联系人 / 升级路径 | 现场填写 | 待填 |

## 11. 已知限制与后续

- API 是单进程多线程的 `ThreadingHTTPServer`，实测 8 并发 QPS 129.7 已够本项目场景；若要上 500+ 并发，应换 `uvicorn + gunicorn` 多 worker，并在前面加真正的反向代理限流。
- `POST /api/gates/refresh` 是**同步**执行子进程（约 10–13 秒），并发时用锁挡住第二次请求（返回 429）。生产应改为异步任务 + 轮询，否则长请求会占满线程池。
- `GET /api/gates` 不鉴权（只含通过数和耗时，不含任何业务数据）；若客户要求全站鉴权，可在 Nginx 层加 Basic Auth，或改成携带令牌读取。
- Mock 模型为确定性输出，不能用于效果验收；接真实模型时替换 `common/llm_client.py` 的 provider，并把成本单价改成真实合同价。
- 限流是单机内存窗口，重启即清零，多副本部署会各自计数——若要跨副本统一限流，需要 Redis 或网关层限流。
- 站点为纯静态 file:// 可开，但生产建议始终走 Nginx（已配缓存与安全头），避免 file:// 下的跨域与缓存问题。
- `deploy.ps1` 的镜像拉取依赖本机加速器可用；客户现场请优先用 9.4 的离线导入方式。
