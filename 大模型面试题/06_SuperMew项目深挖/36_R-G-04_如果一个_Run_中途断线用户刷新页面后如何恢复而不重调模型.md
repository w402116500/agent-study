# R-G-04: 如果一个 Run 中途断线，用户刷新页面后如何恢复而不重调模型？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`SSE, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 依赖后台任务独立运行与数据库持久化事件流，重连时由 after_seq 增量补齐，绝不重启或重调大模型。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

在 DataPilot 中，前端刷新页面**绝对不会导致大模型重新调用**！这是因为我们把 Agent 的执行生命周期与前端 HTTP 连接彻底解耦：Agent 是在后台由异步任务（Celery 或后台协程）基于唯一的 `run_id` 独立驱动的，所有过程事件与中间数据已经在数据库中落库；当用户刷新页面时，前端只是发起一个带 `after_seq=0` 的读取请求，服务端把已经持久化的事件流批量回放出来瞬间还原界面；如果此时后台还在跑，则自动无缝衔接后续实时流，零浪费 Token。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

当数据分析 Run 耗时较长（如复杂图表渲染需 15 秒）且用户中途断线或刷新页面时，系统通过解耦执行与增量回放实现无损恢复：
1. **前后端架构解耦（Background Execution Decoupling）**：
- 客户端断开连接（如浏览器意外刷新）绝不中断服务端的后台执行任务；
- FastAPI 将 Agent 执行包装在独立的 asyncio.Task 或 Celery 后台工作流中，状态机持续向持久化事件流（Redis Stream / PostgreSQL）写入事件。

2. **核心代码：基于序列号 seq 的 SSE 增量恢复与重连回放**：

```python
import asyncio
from typing import AsyncGenerator, Dict, List
from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse

# 模拟持久化事件存储（生产环境使用 Redis Streams 或 Postgres 事件表）
EVENT_STORE: Dict[str, List[Dict]] = {}

async def event_generator(run_id: str, last_seq: int) -> AsyncGenerator[Dict, None]:
    """增量事件重放生成器：从客户端断开时的 last_seq + 1 开始恢复，避免重调大模型"""
    current_seq = last_seq
    while True:
        history = EVENT_STORE.get(run_id, [])
        # 获取客户端尚未接收的新增事件
        new_events = [e for e in history if e["seq"] > current_seq]
        
        for ev in new_events:
            current_seq = ev["seq"]
            yield {
                "id": str(ev["seq"]),
                "event": ev["type"],
                "data": ev["payload"]
            }
            # 若已达终态事件，结束流
            if ev["type"] in ["completed", "failed"]:
                return
                
        # 轮询间隔等待新事件
        await asyncio.sleep(0.5)

# FastAPI 重连端点通过 Last-Event-ID 或 after_seq 获取客户端已收到的最后序号
```

3. **客户端状态幂等恢复与零模型开销**：
- 页面刷新后，前端读取 LocalStorage 中当前会话的 run_id 与 last_received_seq；
- 发起 SSE 重连请求 /api/runs/{run_id}/stream?after_seq=12；
- 服务端仅需在内存/Redis 中拉取历史事件快速重放给前端，前端重新渲染卡片，整个过程 0 Token 开销，大模型无需重新推理。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ Agent 运行宿主在独立后台任务中，与前端 HTTP/SSE 连接生命周期彻底解耦
- ✔️ 刷新页面依靠 after_seq=0 从数据库拉取历史事件，瞬时重绘所有已完成卡片
- ✔️ 通过分布式锁锁定同一 Run，防止并发刷新引发重复模型推理

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果用户刷新页面时，后台的 Agent 任务刚好因为超时被系统中断了，前端重连会拿到什么？

- 🎯 **考官意图**：考察异常边界处理与状态机终态定义。
- 🛡️ **攻防标准应答**：后台任务如果被中断或异常退出，其清理钩子（finally block）必定会向事件流中追加一个固化的终态事件（type='failed', reason='timeout'）。前端重连拿到该事件后，渲染'任务执行超时，请点击重试'的错误卡片，而不是永久处于 loading 旋转状态。
- ⚠️ **避坑要点**：必须说明终态事件的必达性，不能让前端一直处于挂起状态。

###### 🎯 追问对决：Redis Streams 保存事件流有过期时间吗？如何防止内存打满？

- 🎯 **考官意图**：考察生产环境资源治理与持久化策略。
- 🛡️ **攻防标准应答**：Redis Streams 会设置基于长度的裁剪（MAXLEN ~ 1000）并结合 TTL（如设置 24 小时过期）。对于需要长期归档的审计日志，后台异步 worker 会将事件批量落盘转储到 PostgreSQL 的 run_events 表中，保证内存高效且数据可追溯。
- ⚠️ **避坑要点**：不要说永久存 Redis，必须提到 MAXLEN 限制与冷热分层转储。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 恢复机制依赖数据库处于正常健康状态，事件表的写入延时需保持在毫秒级
- 🛑 单 Run 的状态保留期遵循数据归档策略，默认 30 天内支持完整实时回放


---
