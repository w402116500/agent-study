# PY-11: FastAPI 如何处理 `async def` 与同步 `def` 路由？Docker 沙箱/同步 SDK 任务怎样避免阻塞事件循环？

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`FastAPI, 路由调度, 线程池, Docker沙箱`
- **可信级别**：项目事实 / 核心架构

> 💡 **一句话速记结论**：
> async def 跑在主事件循环，普通 def 跑在外部线程池；Docker 任务采用异步子进程完全解耦主事件循环。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

FastAPI 对路由声明有根本性区别：如果声明为 `async def`，函数直接在主线程的单事件循环里跑，一旦有耗时阻塞操作全站卡死；如果声明为普通 `def`，FastAPI 会自动将其扔进底层 AnyIO 线程池执行，不阻塞事件循环。但对于执行 Docker 沙箱或同步 SDK 分析脚本，普通线程池依然受限且消耗宿主机线程。项目中的标准解法是：在 `async def` 路由中使用 `asyncio.create_subprocess_exec` 异步拉起 Docker 容器，并设置 `asyncio.wait_for` 超时看门狗，主进程仅通过异步管道监听输出，实现主服务事件循环的零压力解耦！

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

FastAPI 路由调度机制与 Docker 沙箱/同步 SDK 任务避免阻塞事件循环的工业方案：
1. **FastAPI 对 `async def` 与同步 `def` 的底层分发哲学**：
- **`async def` 路由**：直接由 ASGI 主事件循环（uvloop）单线程驱动。
  - 铁律：**绝对不能包含任何阻塞调用**（如 `time.sleep()`, 原生 `requests.get()`, 同步文件读写, CPU 密集循环）。一旦阻塞哪怕 500ms，整个事件循环将彻底冻结，并发量直接暴跌至 0，所有并发客户端的 SSE 流和心跳瞬间卡死！
- **同步 `def` 路由**：FastAPI 会使用 `anyio.to_thread.run_sync` 将该函数提交到全局默认工作线程池（ThreadPoolExecutor，默认槽位 40 个）中执行。
  - 陷阱：若该接口耗时较长（如调用外部慢接口需要 3 秒），当只有 40 个并发请求涌入时，全局线程池将被彻底打满，后续所有同步路由将陷入长达数秒的队列排队，导致雪崩。
2. **Docker 沙箱执行代码（如 DataPilot Python 分析沙箱）的防死锁调度**：
- **致命反例**：在 `async def` 中直接调用 `subprocess.run(["docker", "run", ...])`。虽然子进程在操作系统层面独立运行，但当前线程被阻塞在 `waitpid()` 操作系统调用上，瞬间冻死主事件循环！
- **标准解法**：必须使用 `asyncio.create_subprocess_exec` 创建非阻塞异步子进程管道，将 I/O 监听注册到事件循环的 epoll / kqueue 中，并结合 `asyncio.wait_for` 设置进程级硬超时。
3. **核心代码：安全异步子进程调度、Docker 隔离与僵尸容器防御**：

```python
import asyncio
import uuid
from typing import Dict, Any

class DockerSandboxRunner:
    def __init__(self, timeout_seconds: float = 5.0, max_memory_mb: int = 512):
        self.timeout = timeout_seconds
        self.max_memory = max_memory_mb

    async def execute_python_code_safe(self, user_code: str) -> Dict[str, Any]:
        """非阻塞拉起 Docker 容器执行代码，严格规避事件循环假死与孤儿进程"""
        container_name = f"sandbox_{uuid.uuid4().hex[:12]}"
        
        # 构造安全沙箱指令：禁网、只读根目录、内存硬限制、自动销毁
        docker_cmd = [
            "docker", "run",
            "--name", container_name,
            "--rm", # 容器退出后物理镜像层自动清理
            "--network", "none", # 物理断网隔离
            f"--memory={self.max_memory}m", # 内存超标直接被 Linux OOM-killer 终结
            "--cpus=1.0", # 限制单核防死循环
            "python:3.11-slim",
            "python", "-c", user_code
        ]

        # 核心关键：使用非阻塞异步子进程拉起，底层挂载到 epoll 事件监听
        process = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            # 异步通信管道读取输出，并施加硬超时守卫
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout
            )
            return {
                "exit_code": process.returncode,
                "stdout": stdout_bytes.decode("utf-8", errors="replace"),
                "stderr": stderr_bytes.decode("utf-8", errors="replace")
            }
        except asyncio.TimeoutError:
            # 发生超时：主进程不能只管自己超时，必须物理强制杀死 Docker 容器
            print(f"[沙箱超时] 容器 {container_name} 执行超时，发送紧急强杀指令！")
            # 异步拉起杀容器命令，绝不能使用同步 os.system 阻塞
            kill_proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await kill_proc.wait()
            # 杀死子进程管道
            try:
                process.kill()
            except ProcessLookupError:
                pass
            raise TimeoutError(f"沙箱代码执行超过硬限制 {self.timeout} 秒被强制中断！")
```

4. **架构设计与排障指南**：
- **同步 SDK 的妥善包装**：若必须使用某些老旧只提供同步阻塞调用的三方 SDK（如某厂商的专有存储 SDK），绝不可直接调用，必须使用 `await asyncio.to_thread(sync_sdk.upload, data)`，且必须对线程池大小配置独立 Limiter 隔离。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ async def 运行在主事件循环内必须非阻塞；普通 def 运行在 40 槽位的全局工作线程池中
- ✔️ 在普通 def 中执行长耗时任务容易打满线程池导致全站同步路由雪崩排队
- ✔️ Docker 沙箱必须采用 asyncio.create_subprocess_exec 异步子进程拉起并绑定超时硬杀死

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：在 Linux 生产环境中，如果直接 `proc.kill()`，会不会导致 Docker 容器本身变成后台僵尸容器（Zombie Container）？如何使用 `--rm` 与容器名联动清理？

- 🎯 **考官意图**：考察 Linux 进程树、Docker daemon 架构与孤儿容器回收机制。
- 🛡️ **攻防标准应答**：会！`asyncio.create_subprocess_exec` 启动的子进程本质上是 Docker CLI 客户端进程，而不是容器内部的执行进程。如果直接调用 `proc.kill()`，只是杀死了宿主机的客户端命令，而 Docker daemon 在后台依然在独立运行那个无头容器，导致死循环代码持续榨干宿主机 CPU，沦为孤儿/僵尸容器。破局方案是两手抓：第一，`docker run` 必须指定 `--name <唯一容器名>` 和 `--rm` 参数；第二，在捕获超时或 Cancel 异常时，异步执行 `docker rm -f <唯一容器名>`，显式向 dockerd 发送 SIGKILL 强行清理容器实例，双重保障绝不残留后台死进程。
- ⚠️ **避坑要点**：不要以为杀掉了本地 python subprocess 就等同于停止了 docker 容器，Docker CLI 和 dockerd 是 C/S 分离架构。

###### 🎯 追问对决：如何通过调整 AnyIO 的线程池大小（`limiter`）来保护关键业务接口，防止同步任务打满线程池导致全站瘫痪？

- 🎯 **考官意图**：考察 Starlette / FastAPI 依赖的 AnyIO 线程池限流机制（CapacityLimiter）。
- 🛡️ **攻防标准应答**：FastAPI 默认使用的 AnyIO 工作线程池最大并发为 40（默认 `CapacityLimiter(40)`）。如果大量请求打入带有长耗时 I/O 的同步路由，所有 40 个槽位被占满后，后续即便是一个仅需 1ms 的轻量同步接口也会在队列中长时间排队。生产解决方案：一是通过 `anyio.to_thread.current_default_thread_limiter().total_tokens = 200` 动态调大全局默认槽位；二是针对重度同步计算任务，实例化独立的 `limiter = anyio.CapacityLimiter(10)`，使用 `anyio.to_thread.run_sync(heavy_task, limiter=limiter)` 实行物理资源池隔离，避免次要业务拖垮全站主干通道。
- ⚠️ **避坑要点**：盲目把线程池开到几千会导致严重的线程上下文切换开销与内存爆炸，线程池配置必须结合宿主机核数与内存综合评估。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 频繁启动短生命周期的 Docker 容器有进程 fork 开销，需通过预热容器池（Warm Pool）技术优化延迟
- 🛑 异步子进程的 stdout 缓冲区必须妥善消费，避免大输出撑爆系统管道


---
