# O-02: 从用户提交一个数据分析问题到拿到 Markdown 答案，DataPilot 经过哪些组件和状态？

- **归属项目**：`DataPilot` | **题目类型**：`简单题` | **难度等级**：`基础` | **核心主题**：`Agent, SQL, SSE, Sandbox`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> DataPilot 经历‘Opening 意图判定 → 计划冻结 → 串行动态工具循环 → 独立 Final Answer → SSE 流式投递’五阶段。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

当用户输入分析问题后：1. Opening 阶段：普通打招呼走 general-task，只有调用 `start_data_analysis(plan)` 才进入分析流程并冻结 Schema 快照；2. 动态循环阶段：模型按需请求 `run_sql_readonly`、`run_python`、`explore_datalink`，自定义串行 ToolNode 逐个审计并执行；3. 最终答案阶段：模型停止调工具后转移至独立的 Final Answer 节点生成整篇 Markdown，与结构化 Evidence 解耦；4. 回放交付：全程所有状态、Audit、Artifact 形成带唯一 seq 的事件，先持久化入库再通过 SSE 广播到前端。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

DataPilot 从用户输入自然语言到前端渲染完整 Markdown 分析报告，经历 5 个端到端状态流转：
1. **Opening 阶段与快照冻结**：
- 用户输入如“对比 2024Q3 华东与华南渠道退货率并绘制柱状图”；
- 系统进入 Opening 阶段，向 LLM 注册启动契约；LLM 必须调用 `start_data_analysis` 声明意图与初步规划；
- 系统在数据库事务中冻结 `schema_revision`(如 v2.4)、`connection_revision`(只读从库) 与 `datalink_graph_version`，生成全局唯一 `run_id` 与 initial_state。

2. **Discovery 与动态工具串行循环**：
- 系统根据规划进入受控循环，仅暴露受限工具（`run_sql_readonly`、`run_python` 等）；
- 每轮循环 LLM 产出工具调用，由 `SequentialToolExecutor` 逐个分发：
  - SQL 提交至 SQL Guard，经 sqlglot AST 校验只读合规并注入 `LIMIT 1000`，在 5s 超时内查库；
  - 产物写入隔离目录，返回脱敏后的中间摘要与 `audit_id` 给 LLM 作为 `ToolMessage`；
  - 若需复杂统计画图，触发 `run_python`，在 Docker 沙箱（512MB/15s/无网）执行脚本，输出图片 artifact。

3. **Final Answer 生成与 SSE 顺序回放**：
- 当 LLM 判定分析完毕停止发起工具调用，系统切断所有数据工具权限，强制跳转至 `final_answer_generator` 节点；
- 提示词挂载全量已验证 Evidence 事实库，强制 LLM 按 `FinalMarkdownPayload` 结构化输出最终 Markdown；
- 后端将所有事件以唯一单调递增的 `seq` 先落库入 PostgreSQL，再通过 FastAPI `StreamingResponse` 以 SSE 推送前端。

4. **核心代码：LangGraph 串行状态调度与 ID 绑定**：
```python
from typing import TypedDict, List, Dict, Any, Optional
import json

class AgentState(TypedDict):
    run_id: str
    messages: List[Dict[str, Any]]
    schema_revision: str
    tool_budget: int
    evidence_store: Dict[str, Any]

async def sequential_tool_node(state: AgentState) -> Dict[str, Any]:
    """自定义串行工具节点：严格保证执行顺序与 tool_call_id 一致性"""
    last_message = state["messages"][-1]
    tool_calls = last_message.get("tool_calls", [])
    tool_messages = []
    
    # 串行遍历模型发出的每一个工具调用，杜绝并发冲突
    for call in tool_calls:
        call_id = call["id"]
        func_name = call["function"]["name"]
        args = json.loads(call["function"]["arguments"])
        
        # 预算扣减与防御
        if state["tool_budget"] <= 0:
            tool_messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps({"error": "BUDGET_EXCEEDED", "msg": "工具调用轮数已达上限"})
            })
            continue
            
        state["tool_budget"] -= 1
        
        # 分发执行并生成受控审计凭据
        if func_name == "run_sql_readonly":
            # 真实执行 SQL 并记录 Audit
            res = {"status": "SUCCESS", "rows": 12, "audit_id": f"aud_{state['run_id']}_01"}
        else:
            res = {"status": "UNSUPPORTED_TOOL"}
            
        tool_messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps(res, ensure_ascii=False)
        })
        
    return {"messages": tool_messages, "tool_budget": state["tool_budget"]}
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ Opening 模式隔离：普通对话与数据分析有严格工具调用准入门槛
- ✔️ 快照版本锁定：冻结 schema/connection revision，保证单次 Run 状态因果一致
- ✔️ 串行安全节点：逐个校验、逐个执行、遇安全阻断立即熔断
- ✔️ Final Answer 独立节点：避免工具循环最后一轮的输出格式混乱与伪造证据
- ✔️ 事件持久化先行：PostgreSQL 落库成功是 SSE 推送的前提条件

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：为什么不在工具循环最后一轮直接让模型输出最终 Markdown？

- 🎯 **考官意图**：考察 Agent 架构的防御性设计、提示词污染隔离与结构化输出保障。
- 🛡️ **攻防标准应答**：如果工具循环与最终回复混用，模型极易产生两类致命缺陷：一是把未经验证的推测或中间调试信息混入最终报告；二是在该输出完整分析结论时又意外触发工具调用进入死循环。通过独立分流节点，进入 Final Answer 时系统彻底剥离所有工具定义，并挂载校验过的 Evidence 事实库与严格的 Pydantic 结构约束，保障回答的准确性与专业排版。
- ⚠️ **避坑要点**：不要回答'只是为了写代码方便'，必须强调是防止工具误调用与保证证据一致性。

###### 🎯 追问对决：前端如果在工具执行期间刷新了浏览器，如何精准恢复运行状态？

- 🎯 **考官意图**：考察前后端状态机设计、SSE 断线重连机制与事件溯源持久化方案。
- 🛡️ **攻防标准应答**：系统所有运行时事件（规划、SQL、沙箱产物、结论）在通过 SSE 推送给前端前，必须首先以递增 seq 写入 PostgreSQL `run_events` 表。前端刷新或断线重连时，携带已收到的最大 `last_event_seq` 请求 `GET /api/runs/{run_id}/replay?after_seq=N`，服务端拉取增量事件一次性重放并恢复图状态，前端状态机瞬间对齐，而无需重新唤醒大模型。
- ⚠️ **避坑要点**：切忌说'重新触发一次模型分析'，这会导致高额 Token 浪费以及执行状态数据不一致。

###### 🎯 追问对决：模型如果生成的 SQL 语法有误，系统怎么让它自我修复？最多允许试几次？

- 🎯 **考官意图**：考察错误反馈机制、反思循环边界与死循环防范策略。
- 🛡️ **攻防标准应答**：当 sqlglot 语法解析失败或数据库引擎返回表字段错误时，系统将其封装为规范化的 `SQL_SYNTAX_ERROR` 或 `COLUMN_NOT_FOUND` 错误结构体，通过 ToolMessage 反馈给模型，并附带精确的错误行号与可用列名提示。系统在图状态中维护 `error_retry_count`，硬编码最多允许自我纠错 2 次，一旦超过阈值立刻终止该工具并提示降级，避免死循环消耗 Token 预算。
- ⚠️ **避坑要点**：不能说'让它无限重试直到写对为止'，必须给出明确的重试上限（2次）与预算熔断保护。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 Discovery 阶段只暴露基础只读探查，不开放写权限与危险高耗时脚本
- 🛑 Final Answer 生成时如果发现事实不一致，只降级标为 partial，绝不自动篡改数字


---
