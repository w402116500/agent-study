# T-E-06: Run 内唯一 `seq` 如何支持断线补发、乱序丢包检测和前端投影？心跳为什么不落库？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`SSE, 断线重连, 协议设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> Run 内单调递增 seq 支撑断线精确重发与乱序校验，心跳作为纯传输层保活严禁落库。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

每个 Run 内的事件分配从 1 开始单调递增的整数 `seq`，由 `UniqueConstraint("run_id", "seq")` 保证绝对唯一性。前端通过 `?after_seq=N` 实现断线增量拉取，并用 `seq` 校验包顺序与丢包重传。心跳（如 `:keepalive` / ping）仅作为传输层协议维持 TCP 链路与穿透代理网关，无业务状态，绝不占用 seq 也绝不落库，防止数据库无意义膨胀。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

Run 内单调递增 seq 的机制、丢包检测与心跳不落库的设计哲学：
1. **Run 作用域内单调递增 seq 机制**：
- 每个 Run 内部拥有独立的原子递增计数器：`seq = 1, 2, 3, ...`。
- **断线补发（Reconnection Catch-up）**：客户端重连时在请求头带上 `Last-Event-ID: 4`，服务端只需执行 `SELECT * FROM events WHERE run_id = :r AND seq > 4 ORDER BY seq ASC`，即可无缝补齐缺失事件。
- **乱序与丢包检测（Gap & Out-of-order Detection）**：客户端维护本地 `expected_seq`。若当前收到 `seq=6` 而上一个事件是 `seq=4`，立即判定发生了丢包，触发客户端暂停渲染并主动发起局部 Replay 同步。

2. **为什么心跳（Heartbeat）坚决不落库**：
- **心跳本质**：纯粹是传输层的“保活探针（Keep-alive Ping）”，用于防止中间 Nginx 代理或云负载均衡器在 60 秒无数据流时静默关闭 TCP 连接。
- **存储污染防灾**：若大模型思考 40 秒，每 3 秒发一次心跳将产生十几个空事件。若将心跳赋予 `seq` 并落库，会导致数据库充斥 90% 的垃圾心跳记录，且客户端回放时还要过滤大量无用事件，浪费带宽与算力。

3. **核心代码：心跳与数据事件双通道分流**：

```python
async def sse_event_stream_generator(run_id: str, last_event_seq: int):
    # 1. 先回放历史缺失的数据事件
    missed_events = await fetch_missed_events(run_id, after_seq=last_event_seq)
    for ev in missed_events:
        yield f"id: {ev.seq}\nevent: {ev.type}\ndata: {json.dumps(ev.data)}\n\n"

    # 2. 进入实时监听流，心跳独立生成（不占 seq，不落库）
    while True:
        try:
            event = await event_queue.get(timeout=3.0)
            yield f"id: {event.seq}\nevent: {event.type}\ndata: {json.dumps(event.data)}\n\n"
        except asyncio.TimeoutError:
            # 传输层轻量心跳注释行，标准 SSE 规范中使用以冒号开头的 comment
            yield ": ping keep-alive\n\n"
```

4. **总结**：传输层保活与领域层事件必须严格物理分离，保证领域事件流的纯粹可溯源。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ run_id 与 seq 联合唯一索引保证单调递增，作为断线补发游标与前端投影校验基准
- ✔️ 客户端重连携带 after_seq 参数，服务端先查库批量补齐再切回实时队列监听
- ✔️ 心跳属于纯传输层保活协议，不分配业务 seq，物理级禁止落库以防存储污染

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果前端断网太久（比如离开电脑 1 小时），重连请求回放 1000 条历史事件，会导致界面卡死吗？

- 🎯 **考官意图**：考察长周期断连重连的流控与快照恢复策略。
- 🛡️ **攻防标准应答**：设计【快照直接恢复（Snapshot Restore）】机制：服务端若检测到差距 `current_seq - last_seq > 100`，不再全量回放上千条微事件，而是直接向前端下发一份最新的综合状态快照包（Full State Snapshot），前端重置本地状态树，兼顾恢复速度与性能。
- ⚠️ **避坑要点**：不要盲目无上限回放超长历史流，超长事件回放是前端内存泄露和浏览器崩溃的高危诱因。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 seq 仅在单个 run_id 内部单调连续，不同 Run 之间的 seq 彼此独立从 1 计数
- 🛑 after_seq 依赖数据库 run_events 表，若该 Run 历史事件被归档清理则无法重连增量拉取


---
