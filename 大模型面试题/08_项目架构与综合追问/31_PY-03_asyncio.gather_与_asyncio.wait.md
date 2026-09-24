# PY-03: `asyncio.gather` 与 `asyncio.wait` 有什么区别？并行检索子问题时如何处理异常和结果顺序？

- **归属项目**：`SuperMew` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`Python, asyncio.gather, asyncio.wait, 并发异常处理`
- **可信级别**：项目事实 / 核心实践

> 💡 **一句话速记结论**：
> gather 偏结果驱动且保序返回，wait 偏状态流转驱动返回完成/未完成集合；并行子检索推荐使用 gather 并设 return_exceptions=True。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

`asyncio.gather` 和 `asyncio.wait` 的核心区别在于'结果抽象方式'：`gather` 是高级 API，关注的是'拿最终结果'，它严格按照入参顺序返回结果列表，最适合明确知道有几个并发子任务需要保序合并的场景；而 `wait` 是低级 API，关注的是'任务完成状态'，它返回 `(done, pending)` 两个 Task 集合，可以设置 `FIRST_COMPLETED` 在首个任务返回时快速响应。在并行检索子问题时，必须给 `gather` 加上 `return_exceptions=True`，这样某个子检索网络抖动报错会作为异常对象返回，而不会直接打断其他正常子检索的结果收集。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

`asyncio.gather` 与 `asyncio.wait` 的核心机制差异及多路子问题并发检索实战：
1. **两者的核心设计哲学对比**：
- **`asyncio.gather`（结果驱动型，Result-Oriented）**：
  - 特性：聚焦于“收集所有并发任务的最终结果”，**严格保序**（返回列表的顺序与传入协程的顺序 100% 一一对应）；
  - 适用：并行向 3 个不同的知识库或多路检索通道请求数据，最后统一合并结果。
- **`asyncio.wait`（状态驱动型，State-Oriented）**：
  - 特性：聚焦于“监控任务集合的执行状态流转”，返回由 `(done, pending)` 构成的两个集合（无序）；
  - 核心参数：支持 `return_when=FIRST_COMPLETED`（首个完成立即返回竞速）或 `FIRST_EXCEPTION`；
  - 适用：多镜像源竞速检索、抢答式超时熔断。

2. **核心代码：多路检索子问题并发调度与异常防御**：

```python
import asyncio
from typing import List, Dict, Any

async def search_sub_question(sub_q: str, timeout: float = 3.0) -> Dict[str, Any]:
    # 模拟检索逻辑
    await asyncio.sleep(0.5)
    return {"query": sub_q, "results": ["chunk_A", "chunk_B"]}

async def execute_multi_retrieval(sub_questions: List[str]) -> List[Dict[str, Any]]:
    """并行检索多个拆解子问题，严密兼顾顺序、超时与局部失败"""
    # 1. 构造带超时保护的协程任务列表
    tasks = [asyncio.wait_for(search_sub_question(q), timeout=2.5) for q in sub_questions]
    
    # 2. 关键参数 return_exceptions=True：
    # 即使某一个子问题查询超时抛出 TimeoutError，也不会中断其他正在检索的任务！
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    clean_results = []
    for idx, res in enumerate(raw_results):
        # 3. 结果保序解包与异常降级
        if isinstance(res, Exception):
            # 针对性记录错误，为该子问题提供空结果降级，防止主流程崩溃
            clean_results.append({"query": sub_questions[idx], "results": [], "error": str(res)})
        else:
            clean_results.append(res)
            
    return clean_results
```

3. **异常处理红线**：
- **默认 `gather` 的致命陷阱**：若不加 `return_exceptions=True`，只要其中 1 个子任务抛出异常，`gather` 会立刻向上抛出该异常，但**其余仍在运行的子任务并不会被操作系统自动取消**，它们会继续在后台无声息地空跑并耗尽系统资源（任务泄漏）；
- **生产铁律**：并行检索合并必须显式声明 `return_exceptions=True`，并对返回列表遍历做 `isinstance(r, Exception)` 显式解包！

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ gather 关注有序结果产出，wait 关注任务完成集合（done, pending）与状态驱动
- ✔️ gather 默认遇到异常立即抛出且不会主动取消其他后台任务，极易引发资源泄漏与上下文中断
- ✔️ 并发子问题检索首选 `gather(return_exceptions=True)`，既保序又能优雅降级局部单点异常

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：在 Python 3.11+ 中，官方为什么更推荐使用 `asyncio.TaskGroup` 替代默认的 `asyncio.gather`？

- 🎯 **考官意图**：考察 Python 3.11+ 结构化并发（Structured Concurrency）的核心演进思想。
- 🛡️ **攻防标准应答**：因为 `TaskGroup` 实现了真正的【结构化并发（Structured Concurrency）】：在使用 `async with asyncio.TaskGroup() as tg:` 时，若组内任意一个子协程发生未捕获异常，`TaskGroup` 会自动且强制取消组内其余所有尚在挂起或运行的兄弟任务，并在所有任务彻底退出后将所有错误打包为 `ExceptionGroup` 一并抛出。彻底消灭了旧版 `gather` 因某个任务报错而导致其他任务变成后台幽灵孤儿任务的顽疾。
- ⚠️ **避坑要点**：不要只说 TaskGroup 语法好看，核心考点在于结构化并发保障生命周期作用域闭环与零任务泄漏。

###### 🎯 追问对决：使用 `asyncio.wait(return_when=FIRST_COMPLETED)` 实现多路检索竞速时，如何安全清理尚未完成的 pending 任务？

- 🎯 **考官意图**：考察任务生命周期主动收敛与资源取消（Cancel Pending Tasks）。
- 🛡️ **攻防标准应答**：必须显式遍历 `pending` 集合执行 `t.cancel()` 并配合 `asyncio.gather(*pending, return_exceptions=True)` 等待其优雅终结！示例代码：`done, pending = await asyncio.wait(tasks, return_when=FIRST_COMPLETED); for t in pending: t.cancel(); await asyncio.gather(*pending, return_exceptions=True)`。如果不手动取消并等待，挂起的任务仍会继续发送网络请求或占用数据库连接，造成不可挽回的后台资源雪崩。
- ⚠️ **避坑要点**：千万不要只取 done 的结果就撒手不管 pending，挂起的任务必须显式 cancel 并 await 收尾。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 `gather(return_exceptions=True)` 要求业务代码必须显式检查 `isinstance(x, Exception)`，否则易引发后续逻辑空指针
- 🛑 不可并发过量协程（如一次性 gather 1000 个任务），必须前置结合 Semaphore 限流


---
