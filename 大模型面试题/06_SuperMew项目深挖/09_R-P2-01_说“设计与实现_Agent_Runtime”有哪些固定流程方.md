# R-P2-01: 说“设计与实现 Agent Runtime”；有哪些固定流程方案被放弃？为什么采用模型按需工具循环？

- **归属项目**：`DataPilot` | **题目类型**：`证据核验题` | **难度等级**：`高难` | **核心主题**：`Agent, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 放弃‘Schema→SQL→Python→Report’四阶段硬编码 DAG，改用 LangGraph 状态机下的模型按需原生 Tool Calling 循环。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

我们最初做过固定 DAG 流水线：强制‘意图识别→固定生成 SQL→固定执行 Python 作图→组装报告’。但在真实企业数据分析中发现致命问题：有的问题只需查两行配置无需 Python，DAG 硬跑脚本白白浪费 8 秒；有的复杂聚合查出结果为空或字段不符，DAG 无法自我纠错直接报错溃败。我们果断重构为 LangGraph 状态驱动的按需工具循环，模型根据上一轮 Observation 自主决策下一轮是继续查 SQL、调 Python 还是结束生成，将多步完成率从 51% 提升至 84%。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

设计与实现 DataPilot Agent Runtime 时的方案权衡与放弃决策如下：
1. **被放弃的固定流程方案（Rigid DAG Pipeline）与致命痛点**：
- 方案原型：采用四阶段固定顺序线性链：`NL2SQL -> SQL 执行 -> Python 制图 -> 报告生成`。
- 致命痛点 1（多表探查失效）：面对“统计 2024Q3 各大区退货率异动原因”时，固定流水线必须在第 1 步把全部可能用到的 7 张宽表全量 DDL 塞给模型。导致 Prompt 占用超 12,000 Token，模型注意力涣散，高频报错“找不到列名”。
- 致命痛点 2（无自愈能力）：一旦 SQL 查出空结果或字段拼错（如 `status='REFUND'` 实为 `'REFUNDED'`），固定流立即死锁崩溃，无法回溯重试。
- 致命痛点 3（不可跳步）：许多业务问题根本不需要 Python 制图（如“华东区大客户是谁”），固定流程却必须空转或输出无意义空图。

2. **采用 LangGraph 模型按需工具循环（ReAct Loop）的架构设计**：
- 引入状态机循环：模型根据中间结果自主决定是继续探查 DataLink 图谱、还是重写 SQL、或是调用 Python 绘图；
- 单独拆分 Final Answer 节点：循环结束后必须经过独立的格式化与证据绑定节点，防止在工具循环最后一轮“顺手输出脏数据”。

3. **核心代码：LangGraph 动态工具循环与状态机定义**：
```python
from typing import Annotated, TypedDict, List, Literal
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, ToolMessage, AIMessage

class AgentState(TypedDict):
    """状态机全局状态契约：只允许受控字段在节点间流转"""
    messages: Annotated[List[BaseMessage], "消息流，采用 append 机制更新"]
    current_step: int                     # 当前执行轮数，硬上限防止死循环
    schema_version: str                   # 冻结的数据库 schema 快照版本
    captured_artifacts: List[dict]        # 执行期间沉淀的可视化图表或数据快照

def router_logic(state: AgentState) -> Literal["tools", "final_answer"]:
    """条件路由分支：判断是继续工具调用还是收敛至最终回答"""
    last_msg = state["messages"][-1]
    # 达到 5 轮硬上限强制终止，防止死循环烧 token
    if state["current_step"] >= 5:
        return "final_answer"
    # 如果大模型最后一条消息包含工具调用，进入工具执行节点
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        return "tools"
    # 否则收敛至 Final Answer 格式化节点
    return "final_answer"

# 构建动态循环图
workflow = StateGraph(AgentState)
workflow.add_node("agent", call_llm_node)       # 大模型推理节点
workflow.add_node("tools", serial_tool_node)     # 受控串行工具节点
workflow.add_node("final_answer", format_node)   # 独立最终报告节点

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", router_logic)
workflow.add_edge("tools", "agent")             # 工具执行完回传模型，形成按需循环
workflow.add_edge("final_answer", END)          # 最终报告输出后彻底终结
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 放弃固定 DAG 是因为无法处理空结果纠错、下钻探索和时延冗余
- ✔️ 采用 LangGraph 状态机支持根据 Observation 动态决定下一步
- ✔️ 自建串行工具调度并严格受控于 5 轮最大预算与状态快照

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果模型在工具循环中反复尝试相同错误参数陷入死循环，如何从图层兜底？

- 🎯 **考官意图**：考察状态机流转防护、死循环检测以及系统可用性硬边界设计。
- 🛡️ **攻防标准应答**：我们在状态机层设计了双重熔断：1) 计数熔断：`current_step >= 5` 时强制跳出循环流转至 `final_answer`；2) 参数指纹去重：维护 `executed_tool_fingerprints` 集合，计算 `tool_name + hash(args)`，一旦同一参数被连续调用 2 次且返回相同报错，图节点直接向消息流注入系统提示'该参数已被验证无效，禁止重复尝试，请降级回答'，打断幻觉复读。
- ⚠️ **避坑要点**：不要只说'设置最大循环次数'，面试官更看重你对相同输入反复死锁的针对性状态阻断与注入提示词引导机制。

###### 🎯 追问对决：动态循环会不会导致 LLM 输出不可控，违背企业级项目的稳定确定性？

- 🎯 **考官意图**：考察受控 Agent（Governed Agent）与开放式 Agent 的本质区别与工程约束手段。
- 🛡️ **攻防标准应答**：DataPilot 是'受控 Agent'而非开放玩具：1) 工具集受严格白名单约束（仅 4 个只读工具）；2) 参数由 Pydantic Schema 强类型拦截；3) SQL 有 sqlglot AST 硬语法只读校验；4) 最终结论必须经由独立的 `final_answer` 模板节点组装，确保格式、证据角标和免责声明严格符合既定 JSON/Markdown 契约，做到'推理路径动态，执行边界硬编码'。
- ⚠️ **避坑要点**：切忌将 Agent 描述成无所不能的黑盒，必须强调输入、中间执行、安全拦截和输出格式的四重确定性防护。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 按需工具循环并非无限制自治，受 5 轮上限与只读 Guard 绝对约束
- 🛑 Discovery 阶段与执行阶段的可用工具集合是受状态严格隔离的


---
