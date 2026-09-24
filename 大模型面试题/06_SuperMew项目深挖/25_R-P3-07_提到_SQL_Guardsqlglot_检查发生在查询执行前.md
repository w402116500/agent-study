# R-P3-07: 提到 SQL Guard；sqlglot 检查发生在查询执行前还是后，blocked Audit 如何保留？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`SQL, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 检查在发往物理库之前前置执行，基于 sqlglot AST 判定；被拦截时在 Audit 表完整保留语句并标记为 BLOCKED。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

检查绝对发生在前置阶段！任何大模型生成的 SQL 字符串，在发往真实数据库之前，必须先经过 `sqlglot` AST 解析器。一旦发现写入操作、多语句或未知表，网关立即在本地抛出 `SQLSecurityException`，物理数据库根本收不到该网络包。即使被阻断，我们依然在数据库 `sql_audits` 表中插入一条完整记录：保留原始危险 SQL、拦截原因、触发规则，并将状态标记为 `BLOCKED`，既满足企业等保合规要求，又让模型能够在下一轮看到拦截原因。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

SQL Guard 的 AST 拦截时序与 BLOCKED Audit 保留机制：
1. **执行前置拦截时序**：
- 静态语法树拦截必须发生在 SQL 被发送到只读数据库实例**之前**；
- 绝不能执行后才发现违规（防事后无法弥补的注入或长查询拖垮库）；
- 即使拦截失败，也绝不能抛弃该次记录，必须在 `sql_audits` 表生成 `BLOCKED` 状态日志供安全溯源。

2. **核心代码：基于 sqlglot 的只读与 LIMIT 强制注入器（含逐行注释）**：
```python
import sqlglot
from sqlglot import exp

class SQLGuard:
    """执行前置 AST 安全语法树防护网"""
    def __init__(self, max_limit: int = 1000):
        self.max_limit = max_limit

    def validate_and_rewrite(self, raw_sql: str) -> str:
        # 1. 解析为 PostgreSQL 语法树
        try:
            tree = sqlglot.parse_one(raw_sql, read="postgres")
        except Exception as e:
            raise ValueError(f"SQL Syntax Invalid: {str(e)}")

        # 2. 严格校验是否为 SELECT 语句（禁止 DDL / DML）
        if not isinstance(tree, exp.Select):
            raise PermissionError("Security Violation: Only SELECT queries are permitted.")

        # 3. 检查并强制注入 LIMIT 1000 防御大表全表扫描
        limit_exp = tree.find(exp.Limit)
        if not limit_exp:
            # 无 LIMIT，注入 LIMIT 1000
            tree = tree.limit(self.max_limit)
        else:
            # 存在 LIMIT，若超过 1000 则强制截断为 1000
            curr_limit = int(limit_exp.expression.this)
            if curr_limit > self.max_limit:
                limit_exp.expression.set("this", str(self.max_limit))

        # 4. 输出标准化只读 SQL
        return tree.sql(dialect="postgres")
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ SQL 校验在发往物理数据库之前完成 100% 前置静态拦截
- ✔️ 基于 sqlglot AST 解析，拦截 DDL/DML、多语句、危险系统函数与跨库表
- ✔️ Audit 表持久化原始 SQL 并标记为 BLOCKED，兼顾安全合规与模型纠错

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果模型生成的 SQL 有语法错误导致 sqlglot 无法解析，系统标记为 BLOCKED 还是 FAILED？

- 🎯 **考官意图**：考察四态审计状态机（PROPOSED, BLOCKED, FAILED, SUCCESS）语义精度。
- 🛡️ **攻防标准应答**：标记为 BLOCKED。因为 sqlglot 语法解析属于进入数据库之前的安全准入阶段，只要未通过语法合法性与只读白名单校验，系统一律判定为准入阻断（BLOCKED）；只有放行给物理数据库执行时发生的运行时错误（如连接断开）才标记为 FAILED。
- ⚠️ **避坑要点**：不能把语法拦截说成 FAILED，BLOCKED 代表网关主动阻断，FAILED 代表物理执行失败，两者审计责任完全不同。

###### 🎯 追问对决：如果 SQL 包含复杂的嵌套子查询，AST 是如何递归遍历所有表的？

- 🎯 **考官意图**：考察基于 AST 语法树的表级深度检测能力。
- 🛡️ **攻防标准应答**：利用 sqlglot 提供的 `tree.find_all(exp.Table)` 生成器方法，AST 会自动递归下钻遍历所有顶层查询、JOIN、FROM 以及 WHERE/HAVING 中的嵌套子查询，提取每一个表名并与只读白名单匹配，任何不在白名单内的隐藏表都会被当场截获。
- ⚠️ **避坑要点**：千万不要说'用正则提取 FROM 关键字后面的词'，嵌套子查询和复杂别名用正则必漏，必须依赖语法树递归遍历。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 sqlglot 负责语法树静态合规，真实的行数超限与运行超时由物理适配器执行器约束
- 🛑 BLOCKED 记录在安全策略下不可物理删除，需遵循企业数据留存合规周期


---
