# PY-04: 一个协程失败时，其他任务是否会被取消？请比较默认 `gather`、`return_exceptions=True` 和 `TaskGroup`。

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`Python, 协程取消, TaskGroup, 结构化并发`
- **可信级别**：项目事实 / 核心机制

> 💡 **一句话速记结论**：
> 默认 gather 遇错抛出但其他任务后台泄漏；TaskGroup 引入结构化并发，一旦报错自动安全取消全组子任务。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

一个协程失败时，其他任务会不会被取消？在默认的 `asyncio.gather` 中，**答案是绝对不会！** 默认 `gather` 只要有一个任务抛错就会立刻向外抛异常，但其余正在运行的任务会被遗忘在后台继续耗电和发请求，造成严重的'孤儿协程'与连接泄漏；若用 `return_exceptions=True`，它会等待所有任务跑完并把异常当结果返回，也不会取消任何任务；而 Python 3.11 引入的 `asyncio.TaskGroup` 实现了真正的'结构化并发'：只要组内任何一个协程失败，系统会自动向组内其他所有活跃任务发送 `cancel()` 取消信号，并等待它们清理完毕后统一向外抛出 `ExceptionGroup`，彻底消灭孤儿任务！

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

协程失败时的任务级联取消行为深度剖析：默认 `gather` vs `return_exceptions=True` vs `TaskGroup`：
1. **三者在异常发生时的行为对比矩阵**：

| 特性维度 | 默认 `asyncio.gather` | `gather(return_exceptions=True)` | Python 3.11 `asyncio.TaskGroup` |
| :--- | :--- | :--- | :--- |
| **首个任务报错时** | 立刻向外抛出该异常 | 压制异常，将其作为普通返回值放入结果列表 | 捕获异常，自动发起级联取消信号 |
| **其余正在运行任务**| **不会被取消**！继续在后台隐式空跑（孤儿泄漏） | 不受任何影响，继续正常执行直到返回 | **立刻被全部物理取消（`task.cancel()`）** |
| **生命周期保证** | 离开调用点时，可能仍有子任务在后台修改状态 | 保证所有任务均执行完毕才返回列表 | **强约束**：必须等所有子任务全部退出才退出上下文 |
| **异常表达形态** | 仅抛出第一个最先报错的单点异常 | 无异常抛出，返回包含 Exception 实例的列表 | 将所有发生的异常打包为 `ExceptionGroup` 抛出 |

2. **核心代码：三者行为全景对照实验**：

```python
import asyncio

async def worker(task_id: int, sleep_sec: float, fail: bool):
    try:
        await asyncio.sleep(sleep_sec)
        if fail:
            raise ValueError(f"Task {task_id} 发生致命错误！")
        return f"Task {task_id} 成功"
    except asyncio.CancelledError:
        # TaskGroup 在发生兄弟异常时会向此处投递 CancelledError
        print(f"Task {task_id} 收到取消信号，安全清理临时资源！")
        raise

# 模式一：默认 gather 的隐患（任务泄漏）
async def demo_gather_leak():
    try:
        # task 1 耗时 0.1 秒报错，task 2 耗时 2 秒
        await asyncio.gather(worker(1, 0.1, True), worker(2, 2.0, False))
    except ValueError:
        # 此处已经捕获异常，但 worker 2 仍然在后台默默继续运行了 2 秒，产生数据污染风险
        pass

# 模式二：现代 Python 3.11+ 结构化并发终极解法
async def demo_task_group():
    try:
        async with asyncio.TaskGroup() as tg:
            # 启动两个并发子任务
            t1 = tg.create_task(worker(1, 0.1, True))
            t2 = tg.create_task(worker(2, 2.0, False))
    except* ValueError as eg:
        # 使用 Python 3.11 新语法 except* 分类捕获异常组
        # 此时 worker 2 已经在 0.1 秒时刻被强行 cancel，绝无泄漏！
        print(f"安全捕获异常组: {eg.exceptions}")
```

3. **架构选型建议**：
- **完全独立的并行检索（允许部分成功）** ➔ 使用 `asyncio.gather(..., return_exceptions=True)`；
- **强关联的事务型操作（一损俱损，一个挂全军撤退）** ➔ 必须使用 Python 3.11+ 的 `asyncio.TaskGroup`。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 默认 gather 遇到错误时其他正在执行的协程不会被取消，会在后台形成孤儿任务与资源泄漏
- ✔️ return_exceptions=True 强制等待全员完成，适合允许局部单点故障的检索召回场景
- ✔️ Python 3.11 TaskGroup 带来结构化并发，单任务报错自动级联取消全组，是现代微服务的安全标准

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：当一个协程接收到 `task.cancel()` 信号后，其内部的 `try-finally` 块或上下文管理器如何保证释放数据库连接？

- 🎯 **考官意图**：考察 Python 协程取消机制与异常传播深度原理。
- 🛡️ **攻防标准应答**：当外部调用 `task.cancel()` 时，事件循环会在该协程当前挂起等待的 `await` 表达式处主动注入一个 `asyncio.CancelledError` 异常。Python 解释器在栈展开时会严格执行所有的 `finally` 块以及 `async with` 退出方法 `__aexit__`。只要我们在代码中规范使用了异步上下文管理器（如 `async with db_pool.acquire() as conn:`），连接归还逻辑就会 100% 得到执行，绝对不会造成数据库连接池句柄泄漏。
- ⚠️ **避坑要点**：不要在 except 块中随意写 bare `except Exception:`，因为从 Python 3.8 开始 CancelledError 继承自 BaseException，若捕获 BaseException 必须重新 raise 抛出。

###### 🎯 追问对决：在外层捕获 `ExceptionGroup` 时，如何使用 Python 3.11 新语法 `except*` 分别针对性处理不同子异常？

- 🎯 **考官意图**：考察 Python 3.11+ `except*` 分组模式匹配实战语法。
- 🛡️ **攻防标准应答**：使用 `try ... except* SpecificError:` 语法：它允许针对 `ExceptionGroup` 内部树状层级中包含的不同子异常类型进行并行切片分流处理。例如：`except* TimeoutError as e: log_timeout(e)` 负责降级超时任务，紧接着写 `except* ValueError as e: trigger_alert(e)` 负责向监控系统报警。未被任何 `except*` 匹配到的子异常会被重新打包向上级调用链继续抛出，实现了极度优雅且粒度清晰的并发错误处理。
- ⚠️ **避坑要点**：注意语法是 `except*`（带星号），不能写成传统的普通 `except`，普通 except 会把整个组当成一个黑盒对象。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 TaskGroup 要求 Python 版本 >= 3.11，旧版本 Python 3.10 需要依赖外部第三方库 anyio 替代
- 🛑 被 cancel 的协程如果内部吞掉了 `CancelledError`，可能导致 TaskGroup 退出时无限挂死等待


---
