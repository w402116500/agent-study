# T-C-10: Run 上下文为什么要固定 schema/connection revision、graph version 和 snapshot，而不能每轮重新读取当前数据源？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`Agent, 快照隔离, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 固定 revision 和数据快照确保执行因果可复现，避免分析中途 Schema 漂移导致幻觉与雪崩。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

一次数据分析 Run 可能持续调用 5~10 轮工具，历时数十秒。若每轮都动态读取最新的外部数据源，一旦业务表在此期间被其他系统增加了字段、删除了列或写入了新脏数据，会导致大模型在 Step 1 看到的表结构与 Step 3 彻底不一致，产生逻辑幻觉；固定 `schema_revision`、`connection_revision` 与输入快照，锁定了绝对静止的事实基准，确保整个推理链条原子一致且完全可复现。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

Run 上下文必须固定三版本快照（Schema/Graph/Data Snapshot）的本质原因：
1. **生产幽灵 Bug 推演**：
- 现象：一个复杂分析 Run 耗时 30 秒，涉及 3 轮查询。第 1 轮查出“待处理订单 500 条”；在第 2 轮查询时，线上业务库恰好发生 ETL 写入或 DDL 变更（新增了列，或批量更新了状态）；模型第 3 轮计算时发现前后数字完全对不上，甚至由于列名变更抛出查询异常。
- 危害：
  - 前后数字逻辑自相矛盾（同一份报表内两个表格数字打架）；
  - 无法进行事后离线回放与合规审计（相同的 User Prompt 在同样代码下无法复现相同结果）。

2. **核心代码：三快照绑定与上下文冻结器**：

```python
import time
from dataclasses import dataclass

@dataclass(frozen=True)
class RunContextSnapshot:
    run_id: str
    datasource_id: str
    schema_revision: str   # 数据库元数据版本（基于 DDL 变更触发的递增版本号）
    graph_version: str     # DataLink 知识图谱生成时间戳/Git Commit
    snapshot_timestamp: float # 数据源快照逻辑时间戳（PostgreSQL 事务隔离点）

class RunContextManager:
    def create_frozen_run_context(self, datasource_id: str) -> RunContextSnapshot:
        """在 Run 创建的第 0 毫秒，锁定全部三大依赖版本"""
        # 1. 抓取当前元数据 Schema 版本号
        schema_rev = self.get_latest_schema_revision(datasource_id)
        # 2. 抓取当前生效的图谱拓扑版本号
        graph_ver = self.get_active_graph_version(datasource_id)
        # 3. 抓取数据库事务可见性位点 (Snapshot LSN / Read Timestamp)
        current_ts = time.time()
        
        return RunContextSnapshot(
            run_id=f"run_{int(current_ts*1000)}",
            datasource_id=datasource_id,
            schema_revision=schema_rev,
            graph_version=graph_ver,
            snapshot_timestamp=current_ts
        )
```

3. **运行指标与审计一致性保障**：
- 数据库只读事务隔离：在 PostgreSQL 中使用 `BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;`，确保该 Run 内部的多条 SQL 查询看到的是完全相同的数据快照。
- 幂等复现性：即使线上数据在 1 分钟后发生了翻天覆地的变化，审计人员依据 `run_id` 冻结的快照也能 100% 还原当时的决策因果链。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 分析全生命周期冻结 Schema 与版本号，消除运行中字段变更导致的推理混乱与幻觉
- ✔️ 本地文件在启动瞬间复制物理快照，实现与其他 Session 和外界文件变更的物理级读写隔离
- ✔️ 静态基准保证了每次数据分析结论具备法律/合规级别的 100% 事后可复现审计能力

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果一个数据源每天更新一次，我们把快照放在 Redis 缓存 24 小时，会不会引发新元数据漏查？

- 🎯 **考官意图**：考察缓存失效模式（Cache Invalidation）与元数据发布通知机制。
- 🛡️ **攻防标准应答**：采用【版本递增 + 变更主动推刷（Write-Through Invalidation）】：平常查询直接读 Redis 缓存中的快照版本；一旦数据库触发 DDL 变更或数据流完成日更，调度器向 Redis 发送失效事件并递增 `schema_revision`，新发起的 Run 立即读取新版本，旧 Run 仍安全使用绑定的旧版本完成收尾。
- ⚠️ **避坑要点**：不要使用固定 TTL 轮询猜测更新，必须基于 DDL 监听或数据调度任务的完成事件显式失效。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 快照隔离仅在单个 Run 内部绝对生效；不同 Run 之间允许通过新事务读取新版本
- 🛑 远程数据源依赖数据库底层的只读事务隔离级别（如 REPEATABLE READ）辅助保证一致性


---


### 模块九：DataPilot Python 隔离沙箱 (Docker Sandbox & IPC, T-D-01 ~ T-D-10)
