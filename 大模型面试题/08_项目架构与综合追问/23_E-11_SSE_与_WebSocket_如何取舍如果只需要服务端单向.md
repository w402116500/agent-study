# E-11: SSE 与 WebSocket 如何取舍？如果只需要服务端单向事件和断线补发，关键契约是什么？

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`通信协议, SSE, WebSocket, 断线重连`
- **可信级别**：项目事实 / 标准规范

> 💡 **一句话速记结论**：
> 服务端单向文本流优先选 SSE，低开销且天然穿透代理；依赖递增 Event ID 与 Last-Event-ID 契约实现补发。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

为什么大模型流式输出选 SSE 而不是 WebSocket？因为 LLM 生成是典型的'客户端发起一次请求，服务端单向持续下发数据'场景。SSE 基于标准 HTTP/1.1 或 HTTP/2，无需建立双向全双工有状态连接，天然完美穿透企业 Nginx 网关、反向代理与 CDN，运维成本极低。实现断线补发的关键契约是：服务端为每个下发事件打上单调递增的 `id: <seq_id>`，客户端断网重连时通过请求头带上 `Last-Event-ID: <seq_id>`，后端从 Redis 消息队列中读取大于该 ID 的事件进行增量补发。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

SSE（Server-Sent Events）与 WebSocket 的深度技术取舍与断线补发契约：
1. **两大技术协议的核心选型矩阵**：

| 评估维度 | Server-Sent Events (SSE) | WebSocket |
| :--- | :--- | :--- |
| **通信流向** | 服务端到客户端的单向流（Server ➔ Client） | 全双工双向实时交互（Client ⇄ Server） |
| **底层协议** | 标准 HTTP/1.1 或 HTTP/2 文本流（`text/event-stream`） | 独立 TCP 协议（通过 HTTP Upgrade 握手切换） |
| **代理与网关** | 天然穿透企业防火墙、Nginx、Cloudflare 等各类反代 | 需特殊配置代理（`proxy_set_header Upgrade`），易被企业防火墙掐断 |
| **断线重连** | 浏览器 `EventSource` 原生支持自动重连与 `Last-Event-ID` | 必须在前端手写复杂的 Heartbeat 心跳、重连退避算法 |
| **业务契约适用性**| **大模型流式打字机、阶段性思考日志、Agent 步骤通知** | 实时多人协同文档、在线竞技对战、音视频双向信令 |

2. **核心代码：基于 `Last-Event-ID` 与 Redis Stream 的断线补发契约**：

```python
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import redis.asyncio as aioredis
import asyncio

app = FastAPI()
r = aioredis.from_url("redis://localhost:6379")

async def event_generator(channel_id: str, last_event_id: str = None):
    # 1. 客户端断线重连时，检查携带的 Last-Event-ID
    if last_event_id:
        # 从 Redis Stream 中拉取缺失的增量历史事件进行补发
        missed_events = await r.xrange(f"stream:{channel_id}", min=last_event_id, count=50)
        for msg_id, payload in missed_events:
            yield f"id: {msg_id.decode()}\nevent: message\ndata: {payload[b'data'].decode()}\n\n"
    
    # 2. 继续监听实时生成的新事件
    while True:
        events = await r.xread({f"stream:{channel_id}": "$"}, block=5000, count=10)
        if events:
            for stream_name, msgs in events:
                for msg_id, payload in msgs:
                    yield f"id: {msg_id.decode()}\nevent: message\ndata: {payload[b'data'].decode()}\n\n"
        # 发送注释型保活心跳，防止反向代理超时掐断连接
        yield ": heartbeat keepalive\n\n"

@app.get("/api/chat/stream/{channel_id}")
async def sse_endpoint(channel_id: str, request: Request):
    # 从 HTTP Header 中标准读取浏览器自动上传的上次最后接收 ID
    last_id = request.headers.get("last-event-id")
    return StreamingResponse(
        event_generator(channel_id, last_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
```

3. **生产实战三大红线**：
- **必须关闭网关缓冲**：反代必须配置 `proxy_buffering off` 或回传 `X-Accel-Buffering: no`，否则 Nginx 会攒够 4KB 才一次性喷出，打字机流式彻底失效；
- **单向交互足矣**：用户输入在前端走普通 HTTP POST，服务端思考与打字走 SSE 单向流，动静分离，架构最稳健。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ LLM 流式场景为单向数据消费，SSE 基于标准 HTTP 拥有极致的代理穿透性与极低运维成本
- ✔️ WebSocket 适合多人协作白板或游戏等强双向交互，在纯内容生成场景属于过度设计
- ✔️ 断线补发依靠服务端单调递增 Event ID 与客户端 Last-Event-ID 请求头联动 Redis 缓冲实现

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：在 HTTP/1.1 环境下，浏览器对同域名的 SSE 连接数有最大 6 个限制，如何避免页面多 Tab 导致连接池耗尽？

- 🎯 **考官意图**：考察浏览器底层限制与现代化 HTTP/2 / SharedWorker 解决方案。
- 🛡️ **攻防标准应答**：两大工程解法：1) 生产环境全量强制开启 **HTTP/2 或 HTTP/3（QUIC）**：HTTP/2 在底层单个 TCP 连接上支持多路复用（Multiplexing），同域名支持数百个并发流，彻底打破 6 个连接的物理限制；2) 在前端引入 **SharedWorker**：多个浏览器 Tab 共享同一个后台长连接，由 SharedWorker 作为中央中继分发给各标签页，节省客户端连接资源。
- ⚠️ **避坑要点**：不要建议用户‘关闭其他标签页’，必须从 HTTP/2 多路复用或前端 SharedWorker 层面解决。

###### 🎯 追问对决：如果后端生成已经全部结束且 Redis 缓存已过期，客户端再带着旧 Last-Event-ID 重连，服务端应如何响应？

- 🎯 **考官意图**：考察异常断线重连超时与业务会话过期契约设计。
- 🛡️ **攻防标准应答**：服务端检查若发现该任务已归档或 Redis 消息已超过最大保留窗口（如 TTL=30分钟），不应保持连接挂起，而应向客户端回传特定的终结事件 `event: session_expired`，并在 data 中提示用户该会话已终结；前端接收后停止自动重连（调用 `eventSource.close()`），并将整个卡片渲染为静态历史记录，提示用户'连接已超时，可刷新页面重新拉取最终归档数据'。
- ⚠️ **避坑要点**：不要让服务端空转持续推送心跳，白白浪费后端连接句柄。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 SSE 仅支持纯 UTF-8 文本流传输，传输二进制多媒体数据效率低于 WebSocket
- 🛑 生产部署 Nginx 时必须显式关闭代理缓冲：`proxy_buffering off;`


---
