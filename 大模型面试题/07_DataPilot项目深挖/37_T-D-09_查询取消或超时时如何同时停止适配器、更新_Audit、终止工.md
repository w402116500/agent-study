# T-D-09: 查询取消或超时时，如何同时停止适配器、更新 Audit、终止工具循环并保证 Run 终态唯一？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`Agent, Docker沙箱, 资源回收`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 全局 RunFinalizer 监听超时/取消/故障，双超时控制并在退出时强制 kill/rm 容器防止僵尸累积。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

每个 Python 沙箱容器启动时都会在 `RunCancelRegistry` 中登记容器 ID 与底层进程句柄；系统在 Python 内部和 Docker 外部设置双重超时（单次脚本硬超时 30 秒）。当用户前端点击取消、任务超时、服务进程意外中断或 Run 到达终态时，统一生命周期收尾器 `RunFinalizer` 会被触发，执行带超时的强制 `docker kill` 与 `docker rm -f`，并清理宿主机临时绑定卷，根除僵尸容器与磁盘泄漏。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

查询取消/超时时协同停止适配器、更新 Audit、终止工具循环并确保终态唯一：
1. **生产故障痛点**：
- 场景：一个大 SQL 查询耗时过长触发 5 秒超时，前端也发起了取消；但应用层捕获异常后，只更新了局部状态，后台数据库连接仍在疯狂扫描，Agent 状态机由于未收到明确终止信号继续调用下一个工具，引发“幽灵任务”与资源雪崩。

2. **核心代码：全链路协同取消与终态唯一保证器**：

```python
import asyncio
from typing import Dict, Any

class ControlledExecutionLifecycle:
    def __init__(self, db_driver, audit_repo, sse_emitter):
        self.db = db_driver
        self.audit = audit_repo
        self.sse = sse_emitter

    async def execute_with_coordinated_cancellation(self, run_id: str, tool_call_id: str, sql: str) -> Dict[str, Any]:
        audit_id = await self.audit.create(run_id, tool_call_id, "RUNNING")
        
        try:
            # 施加硬性应用级 5.0 秒超时熔断器
            result = await asyncio.wait_for(
                self.db.execute_query_with_cancel_token(sql), 
                timeout=5.0
            )
            await self.audit.update(audit_id, "SUCCEEDED")
            return result

        except asyncio.TimeoutError:
            # 1. 立即向物理数据库发送异步 CANCEL 信号（通过 QueryCancelToken 触发 connection.interrupt() 或 KILL CONNECTION）
            await self.db.send_cancel_signal()
            # 2. 状态机与审计标记为唯一的超时终态
            await self.audit.update(audit_id, "TIMEOUT_ABORTED")
            # 3. 广播终止事件至 SSE
            await self.sse.emit(run_id, "run.aborted", {"reason": "SQL_TIMEOUT"})
            # 4. 抛出不可捕获的硬终止中断，阻止 Agent 执行批次中的后续工具
            raise HardRunTermination("执行超时，已触发安全中断")

        except asyncio.CancelledError:
            # 响应客户端主动发起的断连取消
            await self.db.send_cancel_signal()
            await self.audit.update(audit_id, "CLIENT_CANCELLED")
            raise
```

3. **终态唯一性原则（Terminal State Invariance）**：
- 每个 Run 在数据库和分布式存储中拥有且仅拥有一个终态（`COMPLETED`、`FAILED`、`CANCELLED`、`ABORTED`）。
- 一旦产生任一终态，分布式状态锁（Redis Distributed Lock）立即置位，任何延迟返回的工具回调全部被静默丢弃，杜绝状态覆写。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 容器启动同步绑定 RunCancelRegistry，保证全生命周期持有物理资源操作句柄
- ✔️ 采用 Linux 内部命令超时与宿主机异步硬超时双保险，终结死循环脚本
- ✔️ RunFinalizer 在终态、取消或异常时统一执行 kill/rm 强制回收，配合定时巡检消灭孤儿容器

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果在向数据库发送取消信号 (如 connection.interrupt() 或 KILL CONNECTION) 时失败，数据库连接依然在阻塞怎么办？

- 🎯 **考官意图**：考察连接池借还校验与保底物理断连机制。
- 🛡️ **攻防标准应答**：触发连接池毒化隔离：将该连接从活跃连接池中立即剔除（Evict），直接在 TCP Socket 层面强制 close() 关闭连接文件描述符，触发数据库服务端内核检测到对端 EOF 自动释放资源，避免脏连接还回池中污染后续任务。
- ⚠️ **避坑要点**：绝不能把超时的连接放回连接池供下一个请求复用，那样会导致下一个请求读到上一条查询的残留数据。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 单次 Python 脚本最长执行时间硬性卡死为 30 秒，不允许超长离线批处理任务在此运行
- 🛑 清理逻辑保证尽力而为（Best-effort），若磁盘删除发生系统锁占用，记录告警日志由异步进程重试


---
