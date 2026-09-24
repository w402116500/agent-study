# T-C-03: 为什么默认 `ToolNode` 不满足 DataPilot 的 SQL Audit、取消和 seq 约束？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`Agent, LangGraph, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 默认 ToolNode 盲目并发破坏 SQL 审计顺序与单调 seq，且无法感知全局取消信号。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

LangGraph 官方自带的 `ToolNode` 默认行为是利用并发（`asyncio.gather`）同时触发同批次的所有工具调用。但在受控数据分析中：并发会打乱 SQL proposed -> running -> succeeded 的物理审计流水，导致数据库连接争抢与死锁；无法保证 SSE 事件单调递增的 `seq` 序号；更无法在用户点击‘取消’或第一个工具发生严重安全阻断时中途优雅截断后续调用。因此必须自研串行节点。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

为什么 LangGraph 默认 `ToolNode` 无法满足 DataPilot 生产要求：
1. **生产核心诉求与默认组件冲突**：
- **诉求 1：SQL 审计前置与三态流转（Audit proposed ➔ running ➔ succeeded）**：默认 `ToolNode` 只是简单反射调用 Python 函数，无法在执行前向 PostgreSQL Audit 表持久化审计记录。
- **诉求 2：前端实时 SSE 事件序列号（seq）绑定**：工具执行每一步产生日志与进度事件，必须写入自增全局单调 `seq` 并落库，用于断线重连；默认组件完全没有事件总线感知。
- **诉求 3：支持用户主动取消（Cancel）与协同熔断**：用户点击前端“停止生成”，后台必须能向运行中的执行器下发取消信号并终止后续工具；默认 ToolNode 内部没有协同取消上下文。

2. **核心代码：企业级自定义受控 ToolNode 架构**：

```python
from typing import Dict, Any
from langchain_core.messages import ToolMessage

class DataPilotControlledToolNode:
    def __init__(self, audit_service, sse_event_bus):
        self.audit = audit_service
        self.sse = sse_event_bus

    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        last_ai_msg = state["messages"][-1]
        results = []

        for call in last_ai_msg.tool_calls:
            # 检查运行上下文是否已被用户中断
            if state.get("is_cancelled", False):
                results.append(ToolMessage(
                    content="Operation cancelled by user.",
                    tool_call_id=call["id"],
                    name=call["name"]
                ))
                continue

            # 1. 拦截并创建 Proposed Audit 记录（落库）
            audit_id = await self.audit.create_audit_entry(
                run_id=state["run_id"],
                tool_name=call["name"],
                args=call["args"],
                status="PROPOSED"
            )
            # 2. 推送 SSE 事件通知前端正在调用工具
            await self.sse.emit_event(state["run_id"], "tool.start", {"tool": call["name"]})

            # 3. 执行受控逻辑
            try:
                output = await self._execute_safely(call, state, audit_id)
                await self.audit.mark_success(audit_id, output)
            except Exception as err:
                output = f"Error: {str(err)}"
                await self.audit.mark_failed(audit_id, str(err))

            # 4. 回写 ToolMessage
            results.append(ToolMessage(content=str(output), tool_call_id=call["id"], name=call["name"]))
            
        return {"messages": results}
```

3. **结论与演进**：
- 官方 ToolNode 适合极简 Demo；在具有企业合规审计、只读安全隔离、实时推送与精准取消的生产 Agent 中，重写受控 ToolNode 是必经之路。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 官方 ToolNode 默认并发会导致 SQL 审计日志事务交织，破坏合规审计确定性
- ✔️ 并发调度无法保证 SSE 客户端所依赖的全局唯一、单调自增的 seq 序号
- ✔️ 自研串行节点深度集成 RunCancelRegistry，实现细粒度的即时取消与安全阻断短路

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：在并发多租户场景下，自定义 ToolNode 如何防止某个大查询拖死整个 Python 事件循环？

- 🎯 **考官意图**：考察长耗时 I/O 密集与 CPU 密集工具在异步事件循环中的线程池与隔离调度。
- 🛡️ **攻防标准应答**：通过 `asyncio.to_thread` 将底层同步 psycopg2 驱动或沙箱等待任务投递给受限容量的 `ThreadPoolExecutor`，并配置数据库连接超时 `statement_timeout=5000`，确保异步事件循环主线程永远处于无阻塞状态。
- ⚠️ **避坑要点**：不要在 async 函数里直接调用同步阻塞的第三方 SDK，这会导致服务内所有其他用户的 SSE 连接瞬间卡死。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 串行调度不可避免会稍微拉长多工具同时触发时的总耗时，这是为了安全与审计做出的明确妥协
- 🛑 自定义节点依然遵循 LangGraph 节点签名，输入输出与 StateGraph 完全对齐


---
