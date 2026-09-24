# T-D-01: `run_sql_readonly` 从创建 proposed Audit 到 blocked/running/succeeded 的状态顺序是什么？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`Agent, SQL安全, 审计日志`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> SQL 执行严格经历 proposed -> (blocked) -> running -> succeeded/failed 四态，全生命周期落盘不可抵赖。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

`run_sql_readonly` 在执行前必须先在元数据数据库中插入一条状态为 `proposed` 的审计记录（锁定待执行的 raw_sql、Run ID 和时间戳）；随后送入 sqlglot AST 校验，若判定违规，状态立即更新为 `blocked` 并终止执行；若安全通过，状态流转为 `running` 并派发给只读连接池；执行完毕根据结果更新为 `succeeded` 或 `failed`，并记录实际耗时、影响行数与脱敏指纹。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

run_sql_readonly 的四态审计生命周期（Proposed ➔ Blocked/Running ➔ Succeeded/Failed）：
1. **状态流转时序与合规意义**：
- **PROPOSED（已提议）**：大模型刚输出 SQL 文本，未被送入数据库之前立即落库。记录提议时间戳、原始 SQL 文本、数据源 ID 与调用者身份。确保任何违规操作都有迹可查。
- **BLOCKED（已拦截阻断）**：sqlglot AST 语法树检查发现 DDL/DML、黑名单函数、或者未知表列越权。直接在服务端熔断阻断，不发生任何真实物理数据库查询。
- **RUNNING（正在物理执行）**：通过静态 AST 检查与权限审计，向只读只读数据库连接派发查询，施加 `statement_timeout = 5000` 毫秒硬性熔断。
- **SUCCEEDED / FAILED（终态）**：查询执行完毕并完成敏感字段脱敏与行数截断，更新审计表记录实际耗时、扫描行数与脱敏后结果摘要；若抛出执行异常则记录异常堆栈。

2. **核心代码：全流程审计状态机实现**：

```python
import time
from typing import Dict, Any, Optional

class SqlAuditManager:
    def __init__(self, db_pool):
        self.db = db_pool

    async def execute_audited_sql(self, run_id: str, raw_sql: str, datasource_id: str, mask_fields: list) -> Dict[str, Any]:
        # 1. 阶段一：记录 PROPOSED 提议
        audit_id = await self._insert_audit_record(run_id, raw_sql, datasource_id, status="PROPOSED")
        start_time = time.time()
        
        # 2. 阶段二：执行 AST 静态合规审查
        is_safe, block_reason, sanitized_sql = self._ast_guard_check(raw_sql)
        if not is_safe:
            # 审查未通过：直接打上 BLOCKED 标签终结
            await self._update_audit_status(audit_id, status="BLOCKED", error_msg=block_reason)
            raise PermissionError(f"SQL 安全合规拦截: {block_reason}")

        # 3. 阶段三：审查通过，跃迁至 RUNNING
        await self._update_audit_status(audit_id, status="RUNNING")

        # 4. 阶段四：物理执行与脱敏收尾
        try:
            # 执行只读查询，超时硬限制 5 秒
            rows = await self.db.query_readonly(sanitized_sql, timeout_ms=5000)
            # 严格根据 mask_fields 进行数据脱敏处理
            masked_rows = self._apply_masking(rows, mask_fields)
            cost_ms = int((time.time() - start_time) * 1000)
            
            await self._update_audit_status(audit_id, status="SUCCEEDED", execution_ms=cost_ms, row_count=len(masked_rows))
            return {"data": masked_rows, "row_count": len(masked_rows)}
        except Exception as e:
            await self._update_audit_status(audit_id, status="FAILED", error_msg=str(e))
            raise e
```

3. **运行指标与终态互斥保障**：
- 审计记录一旦到达 `BLOCKED` / `SUCCEEDED` / `FAILED` 即为不可逆终态（Immutable Terminal State）。
- 任何网络超时或进程挂死均有清理 Job 扫描超时未更新的 `RUNNING` 记录，打上 `TIMEOUT_ABORTED` 标志，确保审计链完整。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ SQL 触发瞬间先落盘 proposed 状态，从机制上杜绝未审计即执行的漏洞
- ✔️ 安全拦截直接置为 blocked 并记录违规指纹，不留静默黑洞
- ✔️ 终态严格归档为 succeeded 或 failed，完整记录耗时、行数与脱敏元数据

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果数据库在执行查询期间挂起，系统如何确保 RUNNING 状态不会永久卡住？

- 🎯 **考官意图**：考察连接层与分布式审计事务的双重超时熔断机制。
- 🛡️ **攻防标准应答**：双重保障：1) 数据库连接级别配置 `options='-c statement_timeout=5000'`，由 PostgreSQL 引擎在 5 秒时强制中断查询；2) 应用层通过 `asyncio.wait_for(..., timeout=5.5)` 设置应用层安全超时，触发超时直接发送 Cancel 信号并异步更新审计状态为 TIMEOUT_ABORTED。
- ⚠️ **避坑要点**：不能只依赖应用层的超时，一旦应用层超时抛出异常而数据库后台仍在死循环扫描全表，会导致连接池被耗尽。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 sql_audits 属于主系统核心元数据，与被分析的用户业务数据在不同数据库实例上物理隔离
- 🛑 审计日志不可被普通用户修改或删除，具备单向追加写入特性


---
