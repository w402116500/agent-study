# PY-08: FastAPI 的 `Depends` 如何实现依赖注入？数据库会话、配置和权限依赖的生命周期如何管理？

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`基础` | **核心主题**：`FastAPI, Depends, 依赖注入, 生命周期`
- **可信级别**：项目事实 / 架构标准

> 💡 **一句话速记结论**：
> Depends 统一管理依赖构建与生命周期；配合 yield 语法在请求结束时自动归还数据库连接池，彻底消灭连接泄漏。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

FastAPI 的 `Depends` 是一种强大的控制反转（IoC）机制：它允许我们把鉴权函数、配置中心和数据库会话声明为路由入参，FastAPI 在请求到来时自动按 DAG 图解析并注入依赖。对于生命周期管理，FastAPI 支持基于 `yield` 的上下文管理模式：在 `yield` 之前执行依赖初始化（如从连接池获取只读连接），在请求结束（包括异常退出）后自动触发 `yield` 之后的清理逻辑（如关闭连接或提交事务），从架构层面杜绝了连接池泄漏！

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

FastAPI 依赖注入（`Depends`）的底层原理与数据库会话、配置、权限的全生命周期管理：
1. **`Depends` 依赖注入的核心机制与哲学**：
- **机制**：FastAPI 基于**反射（Reflection）与拓扑图（Dependency Graph）**。在路由被调用前，FastAPI 检查函数入参中的 `Depends(get_db)`，递归解析所有前置依赖，按拓扑序依次实例化并注入进路由参数中；
- **核心价值**：实现控制反转（IoC），彻底摆脱在每个接口里手动写 `db = SessionLocal()` 和 `db.close()` 的混乱样板代码，保证资源安全释放与模块单元测试的极度可插拔。

2. **核心代码：三层依赖注入体系与带生命周期的资源安全释放**：

```python
from fastapi import FastAPI, Depends, HTTPException, Header
from typing import AsyncGenerator
import asyncpg

app = FastAPI()

# 1. 依赖项一：只读配置依赖（单例模式，系统启动时初始化一次）
def get_system_config():
    return {"max_query_limit": 100, "env": "production"}

# 2. 依赖项二：安全鉴权依赖（无状态纯逻辑，直接返回解析后的用户信息）
async def verify_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="无效的认证头")
    token = authorization.split(" ")[1]
    # 模拟解析 JWT
    return {"user_id": "u_8848", "tenant": "financial_corp"}

# 3. 依赖项三：数据库会话管理（基于 yield 的全生命周期上下文绑定）
async def get_db_session() -> AsyncGenerator[asyncpg.Connection, None]:
    # 阶段 A：请求到来时，从连接池中借用一个可用连接并开启事务
    conn = await db_pool.acquire()
    tx = conn.transaction()
    await tx.start()
    try:
        # yield 将已就绪的连接注入到具体的路由函数中
        yield conn
        # 阶段 B：路由函数正常执行完毕返回后，执行提交
        await tx.commit()
    except Exception as e:
        # 阶段 C：若业务路由或流式抛出任何异常，立刻安全回滚
        await tx.rollback()
        raise e
    finally:
        # 阶段 D：无论成功还是失败，100% 确保将物理连接归还连接池，严防泄漏！
        await db_pool.release(conn)

# 路由端点：优雅解耦，参数自动就绪
@app.get("/api/v1/orders")
async def list_orders(
    user: dict = Depends(verify_current_user),
    conn: asyncpg.Connection = Depends(get_db_session),
    cfg: dict = Depends(get_system_config)
):
    rows = await conn.fetch("SELECT * FROM orders WHERE tenant = $1 LIMIT $2", user["tenant"], cfg["max_query_limit"])
    return {"data": [dict(r) for r in rows]}
```

3. **依赖生命周期治理铁律**：
- 依靠 `yield` 实现天然的资源生命周期闭环，彻底消灭连接泄漏；
- 测试时直接使用 `app.dependency_overrides[get_db_session] = mock_db`，无需启动真实数据库即可完成单元测试。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ Depends 实现控制反转与单请求内的依赖结果缓存（use_cache=True）
- ✔️ 基于 yield 语法实现上下文自动闭环，在请求结束时由框架强制执行 finally 归还数据库连接
- ✔️ 清晰划分全局单例（lifespan）、请求级依赖（Depends(yield)）与级联权限鉴权链

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：在 FastAPI 中使用流式响应（StreamingResponse）时，基于 `yield` 的 Depends 会在何时触发清理？（注意流式传输完成才会退出依赖上下文）

- 🎯 **考官意图**：考察流式响应与依赖注入生命周期的特殊耦合机制与长连接占用陷阱。
- 🛡️ **攻防标准应答**：重要机制：在返回 `StreamingResponse` 时，基于 `yield` 的 Depends 并不会在接口 return 语句瞬间触发退出清理，而是会**一直保持挂起状态，直到整个流式响应全部输出完毕（即生成器耗尽或客户端断开）后，才会执行 `yield` 之后的清理逻辑**！因此在流式接口中，严禁在全局 Depends 中持有写事务数据库锁，否则在长达 30 秒的流式打字期间该数据库连接一直被独占挂起，会导致数据库连接池被迅速耗尽挂死！应改为在数据准备完毕后立刻主动提交并释放连接，只把纯内存数据交给流式生成器。
- ⚠️ **避坑要点**：绝不能在整个流式过程中长久霸占数据库连接，必须明确依赖的清理是在流完全关闭时才执行。

###### 🎯 追问对决：在编写单元测试时，如何利用 `app.dependency_overrides` 快速替换底层真实数据库依赖为 Mock 数据库？

- 🎯 **考官意图**：考察依赖注入体系在自动化测试与环境隔离中的高级应用。
- 🛡️ **攻防标准应答**：直接在 pytest 中给字典注入 Mock 替换函数：`app.dependency_overrides[get_db_session] = override_mock_db`。当 FastAPI 执行路由前，会优先检索 `dependency_overrides` 字典，若存在键匹配则完全跳过原依赖函数，直接执行 Mock 函数并注入测试数据。测试结束后通过 `app.dependency_overrides.clear()` 清空字典还原环境，实现零侵入、零污染且毫秒级极速运行的单元测试套件。
- ⚠️ **避坑要点**：测试完成后务必记得调用 app.dependency_overrides.clear()，防止污染后续测试用例。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 流式响应（SSE）长连接期间，持有该依赖的数据库连接会被长期占用，建议在流式启动前先读完数据并尽早释放 Session
- 🛑 避免在 Depends 链条中形成复杂的循环依赖


---
