# 第 01 章 · 大模型基础与 API 工程化

> 岗位锚点：JD 原话「理解 LLM/RAG/Agent 的技术边界」「熟悉大模型技术原理」「熟悉大模型相关产品 API 调用」。
> 前置：无。 交付物：一个带重试/超时/结构化输出/成本核算的 LLM 客户端。

## 1. 学完必须能回答的 8 个问题

1. 一句话讲清 token 是什么，为什么"字数 ≠ token 数"，中文通常怎么估。
2. 上下文窗口是硬墙还是软墙？超了会怎样，有哪三种兜底。
3. temperature / top_p / max_tokens 分别控制什么，什么场景必须调到 0。
4. 为什么会幻觉？三种可工程化的降幻觉手段分别是什么（提示、检索、校验）。
5. 一次调用花了多少钱，怎么算出来（输入 token × 单价 + 输出 token × 单价）。
6. 流式（stream）和一次性返回在工程上各有什么代价。
7. 结构化输出（JSON Schema）为什么比"请你输出 JSON"可靠？
8. 什么需求**根本不该**用 LLM（能规则的、要求 100% 确定的、合规不许生成式回答的）。

## 2. 核心知识（只列必须掌握的，不铺开）

- **分词**：BPE / SentencePiece；中文常见 1 汉字 ≈ 0.6–1 token，英文 1 词 ≈ 1.3 token（量级估算用）。
- **上下文预算**：`system + few-shot + 检索片段 + 对话历史 + 输出预留 ≤ 窗口`。这四块的配比就是后面第 02 章 Harness 的起点。
- **采样参数**：`temperature`(随机性)、`top_p`(核采样)、`presence/frequency penalty`、`stop`。抽取类任务 temperature=0。
- **接口形态**：`/chat/completions` 与 `/messages`；OpenAI 兼容协议已成事实标准（国内 Qwen/豆包/DeepSeek 大多兼容）。
- **错误谱系**：429 限流、5xx、超时、上下文超限、内容过滤、JSON 解析失败。**每一种都要有对应处理**，这是"工程化"和"调 API"的区别。
- **成本**：输入/输出 token 分价；缓存命中便宜；流式不省钱但省首字延迟。

## 3. 开源项目索引（真实 star 数，2026-11-25 查）

| 项目 | 用途 | 地址 |
|---|---|---|
| datawhalechina/diy-llm（3.1k★） | 预训练数据→Tokenizer→Transformer→MoE→SFT/对齐，6 个渐进作业，最适合建立"原理全栈"直觉 | https://github.com/datawhalechina/diy-llm |
| Hannibal046/Awesome-LLM（27.5k★） | 论文集散地，按需查不硬读 | https://github.com/Hannibal046/Awesome-LLM |
| WangRongsheng/awesome-LLM-resources（9.1k★） | 中文 LLM 资料总表（含课程/书/工具） | https://github.com/WangRongsheng/awesome-LLM-resources |
| wgwang/awesome-LLMs-In-China（6.5k★) | 国内模型全景，做"模型选型"时必须看 | https://github.com/wgwang/awesome-LLMs-In-China |

学习方式：**diy-llm 只读不训**（读懂 Transformer 前向与 tokenizer 即可），把时间留给应用层。

## 4. 配套代码

```
03-代码实战/ch01_api_baseline/
├─ main.py     # LLMClient：重试退避 / 超时 / 结构化输出校验 / 成本记账
├─ check.py    # L2 闸门：6 条断言
└─ data/cases.jsonl
```

运行：

```powershell
cd 03-代码实战
python ch01_api_baseline/check.py
```

默认走 `common/mock_llm.py` 的确定性 Mock（无需 API key，可复现）。切换真实模型：

```powershell
$env:LLM_PROVIDER="openai_compatible"; $env:LLM_BASE_URL="..."; $env:LLM_API_KEY="..."; $env:LLM_MODEL="..."
python ch01_api_baseline/check.py
```

## 5.【一章一检验】

### L1 概念口试（8 问，讲清 ≥6 且各举 1 反例才算过）

用上面第 1 节的 8 问自测。判据：不看资料，3 分钟内答完；每题必须带一个"什么时候不成立"。

### L2 代码闸门

```powershell
python ch01_api_baseline/check.py
```

期望末行：`[CH01] PASS 6/6`。断言覆盖：

- `A1` 429 触发指数退避且总尝试 ≤3；
- `A2` 超时抛出 `TimeoutError` 而非静默返回空串；
- `A3` 非法 JSON 输出被 schema 校验拦截并触发一次修复重试；
- `A4` 成本计算与手工核算一致（误差 <1%）；
- `A5` 上下文超限时触发裁剪（保留 system + 最近 N 轮）；
- `A6` temperature=0 时两次调用输出一致（Mock 验证）。

### L3 交付物验收（5 项 × 20 分，≥80 过）

| 项 | 要求 |
|---|---|
| 客户端完整度 | 重试/超时/超限/解析四类异常都有处理分支，有日志 |
| 成本表 | 输出一张"单次问答成本 / 1000 次成本"表，含输入输出拆分 |
| 边界判断 | 写 3 个"不该用 LLM"的医疗业务案例并说明替代方案（规则/检索/人工） |
| 可复现 | 别人按 README 跑一遍得到同样 PASS |
| 表达 | 能用 1 页讲清"我怎么处理模型的不确定性" |

### 回炉清单（任一层不过就补这些）

- 讲不清 token → 用 diy-llm 的 tokenizer 章节实际跑一遍分词；
- 不会算成本 → 手算 3 个 case 对账；
- 异常处理漏 → 把错误谱系 7 类逐条写进 `except` 分支；
- 说不出边界 → 读 `01-JD` 报告 C1 那一行，把"能力边界"翻译成 3 个业务判断。

### 通关凭证

> "我实现了一个生产可用的 LLM 客户端：四类异常全覆盖、成本可核算、上下文可裁剪。"

## 6. 常见坑

- 把 `max_tokens` 当成"字数上限"——它是输出 token 上限，设小了会截断在半句话。
- 重试不带抖动（jitter），限流时所有请求同时重试，越重试越堵。
- 用 `eval()` / 正则去解析模型输出——永远用 schema 校验 + 失败重试。
- 只测成功路径。**闸门脚本必须打异常路径**，这是面试里"你做过工程化吗"的分水岭。
