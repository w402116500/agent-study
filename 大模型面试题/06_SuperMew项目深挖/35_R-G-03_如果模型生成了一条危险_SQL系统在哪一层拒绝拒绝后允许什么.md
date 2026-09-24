# R-G-03: 如果模型生成了一条危险 SQL，系统在哪一层拒绝？拒绝后允许什么样的修正？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`SQL, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 在数据网关执行前由 sqlglot 静态语法树阻断；仅允许业务语法或字段名修正，恶意注入与越权直接熔断中断。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

当模型生成危险 SQL 时，系统在**数据网关前置拦截层**进行绝对物理拒绝，物理数据库根本收不到该请求。被拒绝后，系统根据错误性质严格分流：如果只是普通的可恢复错误（如 `GROUP BY` 缺少列、字段名轻微拼写有误、缺少只读限制），网关将其包装为业务受控反馈，允许模型在 1 次机会内修正重写；但如果是恶意越界（如包含 `DROP/ALTER/DELETE` DDL、多语句分号拼接、企图读取系统表），系统直接判定不可修正，立即终止当前 Run 并拉响安全告警！

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

模型生成危险 SQL 时的多层拦截与受控修正机制如下：
1. **拦截时机与层级划分（Multi-Layer Defense）**：
- 第一层（Prompt 声明）：系统提示词要求只读，但大模型存在被越狱风险，属于软约束；
- 第二层（语法树强制拦截，核心防线）：在进入数据库网关执行前，通过 sqlglot 解析为 AST 语法树，坚决阻断任何非 SELECT 语句；
- 第三层（数据库物理账号权限）：数据库用户仅授予只读账号权限（REVOKE ALL; GRANT SELECT），即使前两层失效也无法落盘破坏。

2. **核心代码：sqlglot AST 静态语法审计与 LIMIT 注入**：

```python
import sqlglot
from sqlglot import exp

class SQLSecurityViolation(Exception):
    pass

def audit_and_rewrite_sql(raw_sql: str, default_limit: int = 1000) -> str:
    """sqlglot AST 静态语法深度审计：100% 阻断破坏性操作并强制限制行数"""
    try:
        # 使用 PostgreSQL 方言解析 AST
        statements = sqlglot.parse(raw_sql, read="postgres")
    except Exception as e:
        raise SQLSecurityViolation(f"SQL语法解析失败: {str(e)}")
        
    # 规则 1：严禁多语句批处理执行（防注入堆叠攻击，如 SELECT 1; DROP TABLE）
    if len(statements) != 1:
        raise SQLSecurityViolation("禁止执行多条复合SQL语句")
        
    ast = statements[0]
    
    # 规则 2：强制必须且只能是 SELECT 查询（阻断 INSERT/UPDATE/DELETE/DROP/ALTER）
    if not isinstance(ast, exp.Select):
        raise SQLSecurityViolation(f"违规操作类型: 仅支持只读 SELECT 查询，检测到 {type(ast).__name__}")
        
    # 规则 3：检查是否带有 LIMIT 子句，未带或超限则强制改写注入
    limit_expr = ast.args.get("limit")
    if limit_expr is None:
        # 无 LIMIT 时强制改写注入
        ast = ast.limit(default_limit)
    else:
        # 有 LIMIT 时校验是否超过上限
        user_limit = int(limit_expr.expression.this)
        if user_limit > default_limit:
            ast.set("limit", exp.Limit(this=exp.Literal.number(default_limit)))
            
    return ast.sql(dialect="postgres")
```

3. **拒绝后的自愈与修正策略（Self-Correction Boundary）**：
- **允许修正的场景**：纯语法拼写错误（如表名/字段名不存在，JOIN 条件缺失），将 DB 报错与表结构反馈给 LLM，允许最多 2 轮修正重试；
- **坚决不予修正的场景**：检测到注入攻击（如 UNION SELECT 敏感系统表、DROP 操作），直接熔断报错，记录安全审计日志，严禁让模型猜测越权。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 拦截在前置数据网关通过 sqlglot AST 静态判定，物理库零请求到达
- ✔️ Audit 记录翻转为 BLOCKED 并完整保留原始恶意语句以备审计
- ✔️ 二元分流：普通语法错误允许 1 次机会修正，DDL/注入/越界立即物理熔断中断

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果模型在 SELECT 查询中加入了死锁/大事务查询（例如深分页或全表大笛卡尔积），AST 很难看出来，如何防范？

- 🎯 **考官意图**：考察对深层 SQL 风险（性能拒绝服务攻击）的防御能力。
- 🛡️ **攻防标准应答**：实施双重运行时防护：1) 执行前执行 EXPLAIN 预估 COST，若执行计划评估出的扫描行数超过 100 万或 Cost 超过阈值（如 50000），直接熔断阻断执行；2) 数据库连接级别强制配置 statement_timeout（如 5 秒），一旦超时底层引擎直接 Cancel 查询，释放资源。
- ⚠️ **避坑要点**：不要以为 AST 就能解决所有性能问题，必须结合 EXPLAIN 预估和物理超时设置。

###### 🎯 追问对决：自愈循环中，如果模型在第 2 轮依然生成错误的字段名，系统如何处理？

- 🎯 **考官意图**：考察 Agent 容错与优雅降级策略。
- 🛡️ **攻防标准应答**：配置严格的重试计数器（max_retries = 2）。若连续 2 次重试均失败，立即退出循环，将控制权转给 FinalAnswer 节点，向用户明确指出'尝试查询 [字段名] 失败，知识库中仅包含 [可用字段列表]'，并建议用户修正问题表达，绝不陷入死循环消耗 Token。
- ⚠️ **避坑要点**：回答必须体现可控上限（如 2 轮）和兜底交互友好性。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 SQLGuard 负责语法与安全策略审查，业务逻辑本身的指标合理性需由模型规划保证
- 🛑 对于新型未知方言的语法，需持续更新 sqlglot 解析规则库


---
