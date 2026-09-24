# T-E-09: 历史回放为什么只读事件和 Artifact？如果原数据源已删除，历史 Run 仍能展示什么？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`历史回放, 不可变产物, 灾备与审计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 历史回放仅读不可变事件流与 Artifact，源库即便物理删除，完整分析过程与图表依然可信再现。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

历史回放严格采用只读模式，直接重放 `run_events` 表中的事件流与 `artifacts` 表中的不可变快照，不触发任何工具调用或模型推理。即使目标数据源已物理下线或删除，历史 Run 依然能完整呈现当时的思考步骤、执行的 SQL、脱敏后的表格数据以及 Python 生成的图表图片，因为当时的执行结果已经固化为不可变静态资产。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

弱网与断线重连时客户端主动发起 Sync/Replay 请求的必要性：
1. **为什么必须由客户端主动发起（Client-Driven Sync）**：
- **服务端无法准确感知对端假死（TCP Half-Open 问题）**：移动端在电梯中切换基站或弱网超时，底层的 TCP 连接并未立即触发 RST 包。服务端可能还在继续往悬空的 Socket 写入，误以为客户端已经收到；
- **客户端是状态缺失的唯一真实知情者**：只有客户端清楚自己成功消费并渲染到的最大序列号是几（`last_received_seq = 8`）。因此，重连后必须由客户端显式发起补发握手。

2. **核心代码：客户端重连补发协议与服务端响应**：

```python
from fastapi import APIRouter, Header, HTTPException
from typing import List

router = APIRouter()

@router.get("/api/runs/{run_id}/events")
async def stream_run_events(
    run_id: str, 
    last_event_id: str = Header(default="0", alias="Last-Event-ID")
):
    """
    标准 SSE 补发协议接口：
    客户端重连时自动携带 Last-Event-ID 请求头
    """
    start_seq = int(last_event_id)
    
    # 1. 提取当前已持久化但客户端未见过的后续事件流
    replay_events = await event_store.get_events_after(run_id, after_seq=start_seq)
    
    async def event_generator():
        # 先补发落下的所有历史事件
        for ev in replay_events:
            yield f"id: {ev.seq}\nevent: {ev.type}\ndata: {ev.data_json}\n\n"
        
        # 补发完毕后，无缝桥接实时广播流
        async for live_ev in subscribe_live_channel(run_id):
            yield f"id: {live_ev.seq}\nevent: {live_ev.type}\ndata: {live_ev.data_json}\n\n"

    return EventSourceResponse(event_generator())
```

3. **运行指标与抗弱网收益**：
- 配合指数退避（Exponential Backoff）重试，在移动端地铁、电梯切网场景下，断线恢复率可达 99.8%，用户界面无须刷新网页即可自动补齐缺失内容。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 历史回放只读 run_events 与 artifacts，零重算、零费用、零对外部服务的依赖
- ✔️ SQL 审计记录与输出产物在执行完成时固化，具备天然的防篡改与时间戳凭证特性
- ✔️ 物理数据源下线不影响历史呈现，所有图表与脱敏结果已完全序列化持久化

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果客户端由于长时间断网，重连时该 Run 已经早就彻底执行结束了，服务端怎么处理？

- 🎯 **考官意图**：考察已完成任务（Dead Run）的历史归档回放机制。
- 🛡️ **攻防标准应答**：服务端检查 Run 状态，若已达终态，直接将全部离线事件流（从 `after_seq` 到终态事件）作为普通 HTTP 流一次性推完，并紧接着发送自定义终止帧 `event: stream.close`，客户端收到后主动关闭 EventSource 连接，释放网络资源。
- ⚠️ **避坑要点**：不要一直保持悬空的长连接，已结束的任务推完即闭，杜绝无意义的连接泄漏。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 回放展示的是历史运行当时捕捉的静态事实，不会反映源库在后续产生的任何更新
- 🛑 不可变资产仅保留脱敏后的安全产物，源库中的原始敏感数据不会备份到回放系统中


---
