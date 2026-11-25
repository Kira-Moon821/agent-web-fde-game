# 03 代码实战 · 使用说明

零第三方依赖，Python 3.10+ 即可离线跑通；接入真实模型只改环境变量，不改代码。

## 目录

| 目录 | 对应章节 | 一句话 |
|---|---|---|
| `common/mock_llm.py` | 公共 | 确定性 Mock 模型 + token 估算 + 成本函数 + 故障注入 |
| `common/llm_client.py` | 01 | 重试/超时/裁剪/结构化输出/记账 |
| `ch01_api_baseline/` | 01 | LLM 客户端 + 成本报告 |
| `ch02_prompt_harness/` | 02 | 五层 Prompt 装配 + 上下文预算 + badcase 集 |
| `ch03_rag/` | 03 | 切分→混合检索→带引用作答→拒答→指标 |
| `ch04_agent_tools/` | 04 | 手写 ReAct + 四道约束闸 + MCP manifest |
| `ch05_finetune_data/` | 05 | 数据质检流水线 + LoRA 参数估算 |
| `ch06_eval/` | 06 | rubric 判分 + 回归门禁 + diff |
| `ch07_service/` | 07 | SSE/鉴权/限流/幂等/健康检查/指标 |
| `ch08_deploy/` | 08 | 冒烟 + 压测 + 单位经济模型 |

## 一键验收

```powershell
cd 03-代码实战
python run_all_checks.py
```

期望输出：8 章全部 PASS。

## 单章验收

```powershell
python ch01_api_baseline/check.py     # [CH01] PASS 6/6
python ch02_prompt_harness/check.py   # [CH02] PASS 7/7
python ch03_rag/check.py              # [CH03] PASS 8/8
python ch03_rag/eval.py               # Recall@4 / Accuracy 报告
python ch04_agent_tools/check.py      # [CH04] PASS 9/9
python ch05_finetune_data/check.py    # [CH05] PASS 6/6
python ch06_eval/check.py             # [CH06] PASS 7/7
python ch06_eval/run_eval.py --run v2 --gate   # 演示"安全回归被阻断"
python ch07_service/check.py          # [CH07] PASS 8/8
python ch08_deploy/check.py           # [CH08] PASS 7/7
```

## 接真实模型

```powershell
$env:LLM_PROVIDER="openai_compatible"
$env:LLM_BASE_URL="https://你的服务/v1"
$env:LLM_API_KEY="sk-xxx"
$env:LLM_MODEL="你的模型名"
python ch01_api_baseline/check.py
```

注意：真实环境下 Mock 的故障注入不会自动生效，第 01 章的 A1/A3/A6 断言会因"真实模型不确定"而需要人工判读；建议保留 Mock 作为回归基线，真实模型走第 06 章金标集。

## 代码约定

- 所有"数字"可复现：同样的输入 → 同样的输出、同样的 token 数、同样的成本。
- 每个 `check.py` 只打自己的章节，失败时打印具体断言差异。
- 不写 `eval()`、不裸解析模型输出、不把密钥写进代码。
