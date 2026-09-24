# T-C-01: Opening 如何区分普通文本和 `start_data_analysis(plan)`？为什么普通协议不创建分析工具？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`Agent, 状态机, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> Opening 阶段根据模型协议分流：普通文本走常规回复，仅严格调用 start_data_analysis 才激活分析工具。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

Opening 节点先只向大模型开放基础意图协议。若用户只是闲聊或提问系统能力，模型输出普通文本，系统走 `general-task` 轻量直接回复，杜绝工具资源浪费；只有当模型严格调用了 `start_data_analysis(plan)` 且计划字段通过服务端 Schema 校验与物化后，系统才驱动状态机流转至 `data-analysis` 阶段，并动态将 `run_sql_readonly` 等数据分析工具注入后续 Tool Calling 上下文。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

Opening 阶段区分普通问答与数据分析任务的协议分流机制：
1. **业务场景与意图碰撞**：
- 场景 A（日常寒暄/宏观概念）：“你好，请问你们系统支持分析哪些数据库？”、“什么是同环比分析？”
- 场景 B（真正的数据分析诉求）：“帮我查下华东区上个月退货率最高的 5 家门店，并画出柱状图。”
- 为什么普通对话不能绑定分析工具：如果每个通用问题都向大模型注入 SQL 执行、Python 沙箱等厚重工具 Schema，不仅白白消耗 2000+ System Prompt Token，且极易引发“模型强行调用空 SQL 查系统表”的严重误触发行为。

2. **核心代码：Opening 意图分流与状态机门禁**：

```python
from typing import Dict, Any, Literal
from langchain_core.messages import HumanMessage, AIMessage

def opening_router_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Opening 节点：
    1. 首轮仅挂载轻量意图识别 Prompt 或结构化元路由
    2. 若用户只是普通咨询，直接走轻量快速应答链路
    3. 若属于数据分析需求，模型输出 start_data_analysis(plan) 触发图状态跃迁
    """
    last_msg = state["messages"][-1]
    
    # 检查大模型首轮输出是否包含启动数据分析的显式指令
    if hasattr(last_msg, "tool_calls") and any(tc["name"] == "start_data_analysis" for tc in last_msg.tool_calls):
        call = next(tc for tc in last_msg.tool_calls if tc["name"] == "start_data_analysis")
        analysis_plan = call["args"].get("plan", "常规分析")
        
        # 激活数据分析会话上下文，开放只读 SQL 与探查工具
        return {
            "current_phase": "DISCOVERY",
            "active_tools": ["run_sql_readonly", "explore_datalink"],
            "analysis_plan": analysis_plan,
            "tool_budget_remaining": 6  # 设定严格工具调用配额
        }
    else:
        # 普通会话结束或进入常规沟通
        return {
            "current_phase": "CASUAL_CHAT",
            "active_tools": []
        }
```

3. **运行指标与安全红线**：
- 资源与安全防御：普通对话零数据库连接、零沙箱容器创建；仅当 `start_data_analysis` 明确触发且通过计划校验后，后端才懒加载初始化只读数据库会话，杜绝资源空耗与未授权越权。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ Opening 阶段通过是否存在 start_data_analysis(plan) 将请求严格分流为 general-task 与 data-analysis
- ✔️ 普通对话绝不预先下发 SQL/Python 工具，遵循最小权限原则并收敛 Prompt 注入攻击面
- ✔️ 计划通过服务端校验并物化后，才动态挂载数据分析工具与沙箱资源，避免闲聊时的系统开销

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果用户在普通对话中突然输入 SQL 注入语句（如 DROP TABLE），Opening 阶段会受到影响吗？

- 🎯 **考官意图**：考察前置意图识别阶段的攻击免疫与隔离能力。
- 🛡️ **攻防标准应答**：完全不受影响。因为 Opening 阶段根本没有初始化任何数据库驱动与连接池，也不暴露任何 SQL 执行工具接口。恶意文本仅被当作普通的对话字符串处理，在根源上切断了注入载体。
- ⚠️ **避坑要点**：不要说用正则去过滤用户的 SQL，只要接口不挂载执行工具，任何文本输入都是天然无害的。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 start_data_analysis 只用于确立分析方向，不直接在参数内执行实际数据查询
- 🛑 若已进入 data-analysis 模式，后续同一个 Run 不再允许退回 general-task


---
