# 第 04 章 · Agent、工具调用与 MCP

> 岗位锚点：「Agent 搭建经验」「Multi-Agent」「MCP」「Skills」「各类 Agent 产品」「自己动手搭过 Agent 工具项目（加分项）」。
> 前置：01–03。 交付物：带工具注册 / 权限沙箱 / 步数预算 / 失败兜底的 Agent + MCP 清单。

## 1. Agent 到底是什么（去掉玄学）

**Agent = LLM + 工具 + 循环 + 状态 + 约束。** 五件套：

| 件 | 说明 | 没有它会怎样 |
|---|---|---|
| LLM | 决策器，负责"下一步做什么" | — |
| 工具 | 带 schema 的函数（查库、调接口、发消息） | 只能聊天，不能办事 |
| 循环 | ReAct：思考→行动→观察→再思考 | 单轮问答，无法多步任务 |
| 状态 | 中间结果、已完成步骤、预算余额 | 重复劳动、跑飞 |
| 约束 | 最大步数、超时、花费上限、权限白名单 | **烧钱、越权、死循环** |

> 面试里最容易被问倒的不是"怎么搭"，而是"**怎么让它停下来**"。约束是 Agent 的成人礼。

## 2. 核心知识

### 2.1 工具设计三原则

1. **一个工具只做一件事**，名字即语义（`search_patient_labs` 而不是 `do_query`）。
2. **schema 里写清楚"不许用来干什么"**，比在 system prompt 里写十遍有用。
3. **返回要截断 + 摘要**：工具返回 10 万字，第二次调用就爆上下文。

### 2.2 ReAct 循环的工程实现

```
while step < MAX_STEPS and budget > 0:
    thought, action = llm(history, tools)
    if action is None: return final_answer
    if action not in ALLOWED_TOOLS: return 拒绝 + 记录审计
    observation = tools[action](args)   # 超时 8s，失败重试 1 次
    history.append(...)
else: return 降级答案 + 人工接管标记
```

**四个必须有**：最大步数、单步超时、总预算、审计日志。

### 2.3 上下文窗口管理（Anthropic FDE 面试重点）

- 只保留"事实性观察"，把长工具结果压成 3 行摘要；
- 历史按"已完成 / 待办 / 已否决"三段结构化，而不是原样堆聊天；
- 接近窗口 80% 时触发"存档 + 摘要 + 重开一轮"。

### 2.4 MCP 与 Skills（2026 年的关键词）

- **MCP（Model Context Protocol）**：把工具/资源以标准协议暴露给模型，一次接入、多端复用。要能说清 `tools / resources / prompts` 三类能力与"客户端—服务端"关系。
- **Skills**：把"某类任务的做法"打包成可复用资产（说明 + 脚本 + 素材），和 MCP 的区别是：MCP 给"手"，Skills 给"做法"。
- 面试表述："MCP 解决工具接入的标准化，Skills 解决流程知识的复用，两者都服务于 Harness。"

### 2.5 多智能体什么时候值得

- 值得：任务可分解且子任务需要不同上下文/权限（如"检索员 + 审核员 + 撰写员"）。
- 不值得：单流程任务——多智能体只会增加延迟、成本和不可控性。
- 关键设计：**谁有写权限**。给子智能体最小权限，主控只做编排。

## 3. 开源项目索引

| 项目 | 用途 | 地址 |
|---|---|---|
| shareAI-lab/learn-claude-code（80.9k★） | 手写 agent harness（循环/工具/权限/中断），和本章代码结构几乎同构，强烈建议对着读 | https://github.com/shareAI-lab/learn-claude-code |
| datawhalechina/hello-agents（87.9k★） | 中文《从零开始构建智能体》，ReAct/记忆/多智能体章节完整 | https://github.com/datawhalechina/hello-agents |
| rohitg00/ai-engineering-from-scratch（80.1k★） | Agents + MCP 专题，工程视角补齐生产细节 | https://github.com/rohitg00/ai-engineering-from-scratch |
| tensorchord/Awesome-LLMOps（6.0k★） | Agent 上线后的运维/可观测工具清单 | https://github.com/tensorchord/Awesome-LLMOps |

## 4. 配套代码

```
03-代码实战/ch04_agent_tools/
├─ tools.py          # 工具注册表：schema + 权限级 + 超时 + 返回截断
├─ agent.py          # ReAct 循环：步数/预算/超时/审计/降级
├─ mcp_manifest.json # 一个最小 MCP 服务端能力清单（tools/resources/prompts）
├─ check.py
```

```powershell
python ch04_agent_tools/check.py
```

内置 5 个模拟工具（查患者化验、查药品说明、检索知识库、计算 BMI、提交工单），其中"提交工单"是**写操作**，默认需要二次确认——这正是权限沙箱的检验点。

## 5.【一章一检验】

### L1 概念口试（8 问）

1. Agent 五件套是哪五个？去掉"约束"会发生哪三件事故？
2. 工具 schema 怎么写才算"模型不会用错"？举一个你设计的工具名与描述。
3. ReAct 循环里，"观察"为什么必须截断？
4. 上下文到 80% 时你的处理策略是什么，会丢什么？
5. MCP 与 Skills 的区别，各解决什么问题？
6. 什么任务不该用多智能体？说出两个判据。
7. 写操作工具怎么做出"人在回路"的确认？
8. Agent 跑飞的三种典型形态（死循环/越权/烧钱）各用什么机制防？

### L2 代码闸门

```powershell
python ch04_agent_tools/check.py
```

期望：`[CH04] PASS 9/9`。断言覆盖：工具 schema 校验、非法工具名被拒、超过最大步数触发降级、单步超时生效、预算耗尽停止、写操作未确认被拦、审计日志每条含 step/tool/耗时、长返回被截断、MCP manifest 含三类能力。

### L3 交付物验收（5 项 × 20 分）

| 项 | 要求 |
|---|---|
| 可跑 Agent | 能完成一个 3 步以上真实任务（例：查化验→比对参考区间→生成解释→提交工单） |
| 约束完备 | 四道闸（步数/超时/预算/权限）都有代码与日志证据 |
| MCP 清单 | 一份 manifest，能讲清每个 tool 的入参、权限级、副作用 |
| 失败演示 | 故意让工具报错，展示降级与人工接管路径 |
| 表达 | 能画一张"Agent 状态机 + 约束点"图并讲 3 分钟 |

### 回炉清单

- 只会调框架不会写循环 → 用本章 `agent.py` 手写一遍，禁用任何框架；
- 工具经常调错 → 改名字与描述，加"何时不要用"字段；
- 一跑就烧钱 → 先加步数与预算，再谈效果。

### 通关凭证

> "我手写了一个带四道约束闸与审计日志的 Agent，并通过 MCP manifest 把工具能力标准化。"

## 6. 常见坑

- 让 Agent 自己决定"要不要继续"，却不设上限——模型永远觉得"再试一次就好"。
- 工具返回值直接入上下文（几万字），第二轮就超限。
- 把"多智能体"当卖点，实际单 Agent 加 2 个工具就能做完。
- 没有审计日志，线上出问题无法复盘——这在 toB 交付里是硬伤。
