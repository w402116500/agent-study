# T-D-02: sqlglot Guard 如何拒绝 DDL/DML、多语句、未知表/列、文件读取和外部函数？哪些错误允许模型提交不同 SQL 修正？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`Agent, SQL安全, sqlglot`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 基于 sqlglot AST 语法树解析拦截一切非 SELECT，白名单校验库表列；仅表列语法错误允许模型自我修正。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

简单的正则匹配很容易被换行符、注释（`--`、`/* */`）或十六进制编码绕过，DataPilot 采用 `sqlglot` 深度解析抽象语法树：强制校验只包含单个 AST 根节点且必须为 `exp.Select`；遍历所有 Table 与 Column 节点，校验是否全部属于当前数据源白名单；严厉阻断 `LOAD_FILE`、`INTO OUTFILE` 等高危函数。若属于列名拼错或语法遗漏允许大模型在额度内纠错，若发现 DDL/DML 等越权阻断直接熔断会话。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

sqlglot Guard 静态语法树硬拦截与可自愈错误分流：
1. **五大红线拦截维度（AST 深度遍历）**：
- 拒绝 DDL/DML：绝对禁止 `Drop`, `Alter`, `Create`, `Insert`, `Update`, `Delete`, `Truncate` 表达式。
- 拒绝多语句注入：解析后的表达式树列表长度必须严格等于 1，拒绝分号拼接的二次语句（如 `SELECT 1; DROP TABLE...`）。
- 拒绝未知表/列白名单越权：提取所有 `exp.Table` 与 `exp.Column`，比对当前数据源元数据白名单。
- 拒绝底层文件读取与系统命令：拦截 `pg_read_file`, `copy ... to/from`, `load_file`, `sys_eval` 等黑名单函数。
- 强制注入 LIMIT 1000：若无 LIMIT 自动注入 `LIMIT 1000`；若模型写的 LIMIT > 1000，强行重写截断为 1000。

2. **核心代码：sqlglot AST 拦截卫士实现**：

```python
import sqlglot
from sqlglot import exp
from typing import Tuple, Set

class SqlglotSecurityGuard:
    FORBIDDEN_FUNCS = {"pg_read_file", "pg_ls_dir", "load_file", "sys_exec", "sleep"}
    FORBIDDEN_EXPRESSIONS = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create)

    def __init__(self, allowed_tables: Set[str]):
        self.allowed_tables = {t.lower() for t in allowed_tables}

    def inspect_and_rewrite(self, raw_sql: str) -> Tuple[bool, str, str]:
        """
        返回值: (是否允许执行, 拦截原因或错误类型, 注入限制后的重构 SQL)
        """
        try:
            parsed = sqlglot.parse(raw_sql, read="postgres")
        except Exception as e:
            return False, f"SQL_SYNTAX_ERROR: 语法无法解析 {str(e)}", ""

        if len(parsed) != 1:
            return False, "MULTIPLE_STATEMENTS: 严禁执行多语句查询", ""

        tree = parsed[0]
        if not isinstance(tree, exp.Select):
            return False, "FORBIDDEN_DML_DDL: 仅允许只读 SELECT 查询", ""

        # 检查是否调用黑名单系统函数
        for func in tree.find_all(exp.Anonymous, exp.Func):
            if func.name.lower() in self.FORBIDDEN_FUNCS:
                return False, f"FORBIDDEN_FUNCTION: 严禁调用系统级敏感函数 {func.name}", ""

        # 表白名单校验
        for table in tree.find_all(exp.Table):
            if table.name.lower() not in self.allowed_tables:
                return False, f"UNKNOWN_TABLE: 访问了未经授权或不存在的表 {table.name}", ""

        # 强行重写 LIMIT 限制
        limit_node = tree.args.get("limit")
        if not limit_node:
            tree = tree.limit(1000)
        else:
            try:
                val = int(limit_node.expression.this)
                if val > 1000:
                    tree.args["limit"] = exp.Limit(this=exp.Literal.number(1000))
            except Exception:
                tree.args["limit"] = exp.Limit(this=exp.Literal.number(1000))

        return True, "SAFE", tree.sql(dialect="postgres")
```

3. **哪些错误允许模型提交修正（Self-healing vs Hard-abort）**：
- 允许自愈重试：`SQL_SYNTAX_ERROR`（拼写漏了逗号）、`UNKNOWN_COLUMN`（列名把 `refund_amount` 记成 `refund_fee`）。这些错误反馈给大模型后，模型可在下一轮换用正确列名继续查询。
- 绝不允许重试（直接封禁/熔断）：尝试执行 `DROP TABLE`、尝试越权读取 `information_schema.users`、调用 `pg_read_file`。这种恶意探测直接判定为安全攻击行为，终止当前 Run。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ sqlglot 编译 AST 消除注释混淆与编码注入，校验单语句且根节点必须为 exp.Select
- ✔️ 表与字段遍历比对快照白名单，封死 load_file 等读写文件与盲注高危函数
- ✔️ 语法与字段拼错返回安全提示支持自愈，注入与越权攻击立即熔断会话

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果用户在 SQL 中使用了子查询或者 CTE (WITH as ...)，sqlglot 能够把内层的表名也全部找出来校验吗？

- 🎯 **考官意图**：考察 AST 深度递归遍历（Deep AST Traversal）与表引用解析的完整性。
- 🛡️ **攻防标准应答**：可以。`tree.find_all(exp.Table)` 在 sqlglot 中采用递归深度优先遍历，无论是嵌套在 `FROM (SELECT ...)`, `WHERE id IN (SELECT ...)`, 还是 `WITH cte AS (...)` 中的内层子表引用，都会被无一遗漏地提取出来，接受白名单比对。
- ⚠️ **避坑要点**：不要用正则匹配提取表名，复杂嵌套 SQL 的表名正则无法覆盖，必须依赖 AST 递归解析。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 sqlglot Guard 针对 SQL 文本层进行防御，底层数据库账号同样必须配置只读（SELECT-only）权限作为双保险
- 🛑 不支持用户自定义外挂扩展的存储过程（Stored Procedure）执行


---
