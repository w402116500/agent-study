# PY-02: `async def`、`await` 和事件循环如何协作？为什么在异步路由里调用同步阻塞函数会拖住所有请求？

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`基础` | **核心主题**：`Python, asyncio, 事件循环, 异步阻塞`
- **可信级别**：项目事实 / 核心机制

> 💡 **一句话速记结论**：
> async def 定义协程由单线程事件循环轮流调度；调用同步阻塞函数会霸占线程，导致全站请求与心跳全部雪崩挂死。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

Python 的 `asyncio` 是单线程协作式并发：事件循环就像一个永不停歇的调度员，协程在遇到 `await` 时主动让出执行权，让调度员去处理下一个就绪任务。如果在 `async def` 路由里调用了同步阻塞函数（如 `time.sleep`、`requests.get` 或同步数据库驱动），该同步函数会直接霸占整个主线程，事件循环被物理冻结！在这几秒内，其他所有并发用户的 HTTP 握手、SSE 流式推送、心跳保活全部被迫停摆，表现为系统大面积卡死和连接超时。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

`async def`、`await` 和事件循环底层协作机制与同步阻塞调用的灾难性影响：
1. **事件循环与协同式调度的物理机制**：
- **单线程驱动**：`asyncio` 默认在**单线程**中运行一个死循环（Event Loop），维护就绪任务队列（Ready Queue）与 I/O 监听器（基于 Linux `epoll` 或 Windows `IOCP`）；
- **主动让出机制**：`async def` 创建协程对象，当执行到 `await some_coro()` 时，若底层遇到网络 I/O 阻塞，协程会主动将控制权 **`yield` 交还给事件循环**，事件循环立即转去调度执行其他已就绪的协程；
- **唤醒通知**：操作系统完成网络数据读写后，在下一轮循环中将挂起的协程重新加入就绪队列恢复执行。

2. **为什么在异步路由里调用同步阻塞函数会拖垮全站所有请求**：
- **霸占唯一线程**：如果在 FastAPI 的 `async def endpoint()` 中写了 `time.sleep(5)` 或同步的 `requests.get(...)`，该同步调用是**硬阻塞操作，绝对不会向事件循环让渡控制权**；
- **全站冻结（Event Loop Starvation）**：在这 5 秒内，**整个 Python 进程被彻底定格挂起**！其余正在并发等待 SSE 流式打字的所有用户、心跳健康检查路由（`/healthz`）全部停滞，Nginx 或 Kubernetes 网关会因为收不到心跳判定服务死亡而强制重启 Pod，引发全局雪崩。

3. **核心代码：同步阻塞函数的正确隔离解耦实践**：

```python
from fastapi import FastAPI
import asyncio
import time
import requests

app = FastAPI()

def legacy_sync_query(url: str) -> str:
    """这是一个遗留的第三方同步阻塞 SDK 调用"""
    # 模拟阻塞 3 秒
    time.sleep(3)
    return "ok"

# ❌ 错误示范：致命毒药！直接拖垮整个服务的所有并发连接
@app.get("/bad")
async def bad_route():
    # 在主事件循环中直接调用同步阻塞函数，导致全站所有用户卡死 3 秒
    res = legacy_sync_query("http://example.com")
    return {"res": res}

# ✅ 正确示范：委派给外部线程池，保护主事件循环永远畅通
@app.get("/good")
async def good_route():
    # asyncio.to_thread 内部由独立工作线程池执行，主事件循环通过 await 立即去调度其他请求
    res = await asyncio.to_thread(legacy_sync_query, "http://example.com")
    return {"res": res}
```

4. **架构准则**：
- 只要声明了 `async def`，函数体内部由头到尾**必须全量使用非阻塞异步生态**（`httpx.AsyncClient` 替代 `requests`，`asyncpg` 替代 `psycopg2`）；
- 若必须调用遗留同步代码，必须包裹在 `asyncio.to_thread` 或直接声明为普通 `def` 路由。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ asyncio 依赖协程在 await 时主动出让 CPU，本质是单线程事件驱动
- ✔️ 在 async def 中调用同步阻塞代码会直接冻结主线程，导致全站所有长连接与流式输出瞬间停滞
- ✔️ 必须全链路原生异步化，遗留同步库必须用 asyncio.to_thread 包装或声明为普通 def 路由

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如何在 CI 静态代码检查或单元测试中，自动化检测代码里是否有偷偷调用的同步阻塞网络库？

- 🎯 **考官意图**：考察工程化代码规范检测与异步反模式防护手段。
- 🛡️ **攻防标准应答**：两大工程防线：1) 在代码静态检查中使用 **flake8-async** 或 **ruff** 的异步规则集，静态扫描禁止在 `async def` 作用域内 import 或调用 `requests`、`time.sleep` 等知名阻塞库；2) 在测试环境中开启 `asyncio.get_event_loop().set_debug(True)`，并将 `loop.slow_callback_duration = 0.1` 设为 100ms，一旦某个回调霸占主线程超过 100ms，运行时会自动打印带有具体行号的 WARNING 警告日志。
- ⚠️ **避坑要点**：不要指望靠肉眼排查，一定要上自动化静态 Linter（ruff/flake8-async）与 asyncio debug 模式。

###### 🎯 追问对决：当使用 `asyncio.to_thread` 委派大量同步任务时，底层线程池满载会不会引发拒绝服务？

- 🎯 **考官意图**：考察 AnyIO/asyncio 线程池默认上限与背压控制。
- 🛡️ **攻防标准应答**：会！FastAPI 底层的 AnyIO 线程池默认最大工作线程数是 40 个。若瞬时涌入 100 个需要耗时 5 秒的同步任务，线程池瞬间打满，后续新任务将排队等待线程释放，表现为严重的接口超时延迟。防护方案是：通过信号量 `asyncio.Semaphore(30)` 显式设置并发硬上限实施背压（Backpressure），超出配额的请求快速返回 429 或进入消息队列，坚决防止无休止排队压垮内存。
- ⚠️ **避坑要点**：不要误以为 to_thread 是万能药可以无限制创建，线程资源极其宝贵，必须配合信号量做并发上限管控。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 `asyncio.to_thread` 虽然解除了事件循环阻塞，但受制于 GIL，多个线程池任务无法在 CPU 上并行加速
- 🛑 频繁的线程切换依然会带来轻微的内存与上下文切换开销


---
