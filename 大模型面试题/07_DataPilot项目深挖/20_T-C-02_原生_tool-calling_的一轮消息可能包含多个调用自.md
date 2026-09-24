# T-C-02: 原生 tool-calling 的一轮消息可能包含多个调用；自定义串行节点如何按返回顺序执行并写回对应 `tool_call_id`？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`Agent, Tool Calling, 并发控制`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 自定义串行节点按模型返回顺序逐个执行工具，严密对齐原始 tool_call_id 并按序生成 ToolMessage。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

当大模型在一轮推理中返回多个并行工具调用列表时，DataPilot 坚决不使用并发协程，而是由自定义串行节点按返回的列表顺序（0, 1, 2...）同步排队执行。前一个工具执行完毕、生成对应事件并递增全局 `seq` 后，才启动下一个；每个工具的输出都封装为独立的 `ToolMessage`，其 `tool_call_id` 严格与模型最初下发的 ID 完全对齐，确保大模型上下文协议一致。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

原生 Tool-calling 批量调用的串行执行、按序写回与 tool_call_id 闭环：
1. **业务场景与模型特性**：
- 场景：大模型在分析复杂报表时，单轮返回 3 个并行调用：`[ToolCall(id="tc_01", "run_sql", {"sql": "SELECT 1..."}), ToolCall(id="tc_02", "run_sql", {"sql": "SELECT 2..."}), ToolCall(id="tc_03", "run_python", {...})]`。
- 致命风险：OpenAI / 通义千问等协议严格要求下一轮必须返回完全对应的 `ToolMessage(tool_call_id=...)`。若并发执行乱序返回、或漏写某一个 `tool_call_id`，模型接口会立即抛出 `400 Invalid parameter: messages` 协议崩溃。

2. **核心代码：自定义串行工具执行节点与回写机制**：

```python
from typing import List, Dict, Any
from langchain_core.messages import ToolMessage, AIMessage

async def serial_custom_tool_executor(state: Dict[str, Any], tool_registry: Dict[str, Any]) -> Dict[str, Any]:
    """
    自定义串行执行节点：
    1. 严格按模型生成的 tool_calls 列表顺序逐个执行
    2. 为每一个调用构建匹配其 tool_call_id 的 ToolMessage
    3. 支持中间故障熔断与状态透传
    """
    last_ai_msg: AIMessage = state["messages"][-1]
    tool_calls = getattr(last_ai_msg, "tool_calls", [])
    
    new_tool_messages = []
    
    for tc in tool_calls:
        call_id = tc["id"]
        tool_name = tc["name"]
        tool_args = tc["args"]
        
        # 1. 安全检查与工具分发
        if tool_name not in tool_registry:
            result_str = f"Error: 未知工具 {tool_name}，当前环境不支持调用。"
        else:
            try:
                # 串行执行，确保前后依赖与 Audit 事务按顺序落地
                tool_func = tool_registry[tool_name]
                result_str = await tool_func(tool_args, state)
            except Exception as e:
                result_str = f"Execution Failure: 工具执行异常 {str(e)}"
        
        # 2. 关键闭环：严密绑定对应的 tool_call_id 构造 ToolMessage
        tool_msg = ToolMessage(
            content=str(result_str),
            name=tool_name,
            tool_call_id=call_id
        )
        new_tool_messages.append(tool_msg)
        
    # 3. 将生成的消息列表整体追加回上下文状态
    return {"messages": new_tool_messages}
```

3. **运行指标与保障细节**：
- 协议完整性验证：不管工具执行成功与否，每个 `tool_call_id` 必定对应一条 `ToolMessage`。即使工具抛出未捕获异常，也在外层兜底转为错误文本回传给模型，绝对不使消息链路出现孤儿 `tool_call_id`。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 拒绝并发执行，按列表原有顺序单线程排队驱动每一个 ToolCall
- ✔️ 每个工具执行前注入全局取消与超时检查，前序失败或取消时可安全熔断
- ✔️ 严格保持 tool_call_id 原样写回 ToolMessage，严防协议错位导致大模型崩溃

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果第二条 SQL 发生了语法错误，第三条 Python 脚本依赖第二条的数据，此时继续执行还是跳过？

- 🎯 **考官意图**：考察批处理工具调用的错误级联与中断决策。
- 🛡️ **攻防标准应答**：采用【即时熔断标记 + 占位消息回传】：检测到强前置依赖的工具执行失败后，中断后续工具的真实物理执行；但为了满足模型协议闭环，对后续未执行的调用自动生成带自身 `tool_call_id` 的 ToolMessage，内容填充为‘由于前置依赖工具执行失败，本步骤已自动取消’。
- ⚠️ **避坑要点**：千万不要直接丢弃未执行的 tool_call，一旦消息列表缺少对应的 tool_call_id，整轮会话直接报 400 彻底死锁。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 即使两个 SQL 完全互不相关，在 DataPilot 内部也严格串行执行以保证审计顺序绝对确定
- 🛑 不支持跨多个物理进程分布式抢占同一个 Run 内的子 ToolCall


---
