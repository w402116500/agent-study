# PY-07: 装饰器和 `functools.wraps` 解决什么问题？哪些耗时/审计逻辑适合放装饰器，哪些不适合？

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`基础` | **核心主题**：`Python, 装饰器, functools.wraps, 元编程`
- **可信级别**：项目事实 / 核心规范

> 💡 **一句话速记结论**：
> 装饰器实现切面关注点分离；wraps 解决函数名与 doc 丢失；只做无状态横切，复杂业务流严禁滥用。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

装饰器本质是高阶函数，利用闭包在不修改原函数源码的前提下为其附加横切关注点（Cross-cutting Concerns）；必须加上 `@functools.wraps(func)`，否则原函数的 `__name__` 和文档注释会被包装器覆盖，导致 FastAPI 路由解析和反射调试彻底失真。工程实践中，通用的耗时统计、接口签名校验、自动异常捕获和权限鉴权极适合做成装饰器；而具有复杂内部业务状态流转、需要深度交互上下文的调度逻辑，绝对不适合放装饰器，滥用会导致代码极其隐晦、难以单测和排障。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

装饰器与 `functools.wraps` 的核心作用、元编程机理与适合/不适合包裹的逻辑边界：
1. **装饰器的本质与 `functools.wraps` 解决的致命问题**：
- **本质**：利用 Python 函数是一等公民（First-class Object）与闭包特性，在不修改原函数源码的前提下，实现横切关注点（AOP，面向切面编程）的解耦分离；
- **致命缺陷（不加 wraps）**：当用装饰器包裹一个函数时，原函数的元数据（函数名 `__name__`、文档 `__doc__`、函数签名 `__annotations__`）会被替换为内层闭包 wrapper 的元数据。这会导致：
  1. FastAPI 的路由文档（Swagger/OpenAPI）全部显示为 `wrapper`，且依赖注入与参数校验彻底瘫痪；
  2. 日志与链路追踪打出的函数名全部错乱，严重干扰排障。
- **解法**：`@functools.wraps(func)` 会将原函数的全部元数据完整拷贝还原到闭包对象上，保证外部观察时函数行为完全透明。

2. **核心代码：生产级异步审计耗时通用装饰器**：

```python
import functools
import time
import logging
from typing import Callable, Any

logger = logging.getLogger("audit")

def audit_tool_execution(tool_type: str = "default"):
    """通用的工业级异步审计与耗时监控装饰器"""
    def decorator(func: Callable[..., Any]):
        # 必须且务必使用 wraps，完整保留原函数的签名、文档与名字
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_ts = time.time()
            func_name = func.__name__
            try:
                # 记录前置审计日志
                logger.info(f"[TOOL_START] 执行工具: {func_name}, 类型: {tool_type}")
                result = await func(*args, **kwargs)
                elapsed_ms = int((time.time() - start_ts) * 1000)
                logger.info(f"[TOOL_SUCCESS] 工具 {func_name} 执行耗时: {elapsed_ms}ms")
                return result
            except Exception as e:
                elapsed_ms = int((time.time() - start_ts) * 1000)
                logger.error(f"[TOOL_FAILED] 工具 {func_name} 耗时: {elapsed_ms}ms, 异常: {str(e)}")
                # 忠实向上抛出原异常，严禁无故吞掉异常
                raise e
        return async_wrapper
    return decorator
```

3. **哪些逻辑适合放装饰器，哪些严禁放装饰器**：
- **适合包裹在装饰器中（纯无状态横切）**：
  1. 接口/工具的耗时统计与 Prometheus 埋点；
  2. 结构化入参/出参的统一脱敏审计落盘；
  3. 网络抖动时的固定次数指数退避重试（Retry）；
  4. 权限认证与 Token 格式有效性拦截。
- **严禁包裹在装饰器中（涉及核心业务逻辑流）**：
  1. 复杂的长事务提交与数据补全回滚；
  2. 针对特定业务实体的复杂多分支业务校验；
  3. 含有动态状态机转移或上下文依赖的大模型推理自愈流程（强行用装饰器会让代码晦涩难懂，极难调试）。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 装饰器利用高阶函数与闭包实现无侵入的切面逻辑分离
- ✔️ 必须添加 functools.wraps 保留原函数的元数据与签名，避免破坏 FastAPI 的反射解析与 Swagger 文档
- ✔️ 耗时监控、自动重试和无状态鉴权适合做切面装饰，强耦合的业务状态流转严禁放入装饰器

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如何编写一个既能装饰同步函数又能装饰 `async def` 异步函数的通用兼容装饰器？

- 🎯 **考官意图**：考察高级元编程与 `inspect.iscoroutinefunction` 动态判定实践。
- 🛡️ **攻防标准应答**：通过 `inspect.iscoroutinefunction(func)` 在装饰器加载阶段动态分流！示例：外层检测若 `inspect.iscoroutinefunction(func)` 为 True，则返回包含 `async def async_wrapper(*args, **kwargs): ... await func(...)` 的异步闭包；若为 False，则返回普通的同步闭包 `def sync_wrapper(*args, **kwargs): ... func(...)`；两个闭包均使用 `@functools.wraps(func)` 修饰，从而使同一个装饰器对 FastAPI 的同步路由与异步路由实现 100% 无缝兼容。
- ⚠️ **避坑要点**：不要用一个 async 闭包去包装同步函数，这会强制将普通同步函数包装为协程对象，破坏原调用链的执行语义。

###### 🎯 追问对决：如果一个函数同时被 3 个装饰器修饰，它们的执行顺序是怎样的？（加载自下而上，执行自外向内）

- 🎯 **考官意图**：考察装饰器语法糖执行时序的底层本质（Decorator Stacking Order）。
- 🛡️ **攻防标准应答**：经典口诀：【加载时自下而上（洋葱由内而外包裹），运行时自外向内（洋葱由外而内剥开）】！当写成 `@dec_A \n @dec_B \n def foo()` 时，语法糖等价于 `foo = dec_A(dec_B(foo))`；因此在模块导入加载时，先执行 `dec_B` 包装 `foo`，再执行 `dec_A` 包装 `dec_B` 的返回值；而在真正发起函数调用时，先进入 `dec_A` 的前置逻辑，再进入 `dec_B` 的前置逻辑，然后执行核心函数 `foo`，最后按逆序退出 `dec_B` 与 `dec_A`。
- ⚠️ **避坑要点**：千万不要混淆‘加载导入时’与‘实际运行时’的时序区别，必须说清包装自下而上、执行自外向内。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 装饰器执行时处于函数的声明周期或调用入口，切忌在装饰器内部持有长生命周期的全局可变状态
- 🛑 过深的装饰器嵌套会增加代码调试和单步断点时的思维负担


---
