# T-E-03: 没有图谱、建图失败和服务临时不可用时，为什么只能 Schema-only 降级，不能伪造语义证据？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`DataLink, 优雅降级, 系统边界`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> DataLink 故障时仅降级为 Schema-only 真实 DDL，严禁脑补伪造语义，守住事实底线。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

当图谱未建、构建失败或 FastMCP 超时不可用时，系统绝不阻断主分析流程，而是退回 Schema-only 降级模式。工具调用返回软失败的 `ToolObservation`，告知模型语义服务暂不可用；同时系统将降级警告记入运行状态并在最终答案快照中明示。架构上严禁大模型或网关脑补虚构语义关系，杜绝错误 Join 导致笛卡尔积或业务事实错误。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

图谱故障时坚守 Schema-only 降级，严禁伪造语义证据的铁律：
1. **业务场景与底线思维**：
- 故障场景：Neo4j 容器维护宕机、或新接入的数据源尚在后台离线建图队列中（图谱为空）。
- 错误诱惑：某些系统为了“让分析继续走下去”，让大模型凭借通用常识“脑补”两者之间的关联关系（例如猜测 `orders` 和 `users` 一定通过 `user_id` 连接）。
- 致命后果：大模型猜测的 Join 条件一旦与真实数据库字段有细微偏差（例如真实字段是 `creator_uid`），导致 SQL 执行报错或产生毁灭性的笛卡尔积错误数据，生成完全颠倒黑白的商业决策分析。

2. **Schema-only 降级标准链路**：
- 彻底屏蔽图谱语义提示，退化为仅从 PostgreSQL `information_schema` 提取的硬性表结构与物理主外键约束（Raw Foreign Keys）；
- 在 Prompt 系统提示词中追加显式降级警告标记：`[SYSTEM_DEGRADATION: 语义图谱不可用，仅提供物理表名与列名，请审慎核对关联列]`。

3. **核心代码：自适应熔断降级中间件**：

```python
class GraphDegradationRouter:
    def __init__(self, datalink_client, pg_metadata_service):
        self.datalink = datalink_client
        self.pg_meta = pg_metadata_service

    async def get_exploration_context(self, datasource_id: str, focus: str) -> dict:
        try:
            # 尝试走 DataLink 知识图谱丰富语义
            return await self.datalink.query(datasource_id, focus, timeout=1.5)
        except Exception as e:
            # 捕获任何网络、超时、宕机异常，触发 Schema-only 确定性降级
            raw_schema = await self.pg_meta.get_raw_columns(datasource_id, focus)
            return {
                "source": "RAW_DATABASE_SCHEMA_ONLY",
                "semantic_enrichment": None,
                "is_degraded": True,
                "tables": raw_schema,
                "warning": "DataLink 图谱服务离线，当前仅依据数据库物理字段进行探查，严禁过度推测未经证实的业务含义。"
            }
```

4. **总结**：在企业级严谨数据分析场景下，**“有据可查的保守”永远胜过“看似聪明的编造”**。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ DataLink 定位为可选语义插件而非强依赖，服务崩溃时通过 ToolObservation 软失败优雅降级
- ✔️ 降级后严格依托真实 DDL 继续分析，绝不使用模型幻觉脑补跨表关系与枚举字典
- ✔️ 降级状态全程可追踪，在状态快照与最终答案中显式注入 Schema-only 审计告警

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：降级为 Schema-only 后，如果两个表根本没有建立数据库物理外键，模型如何推断关联字段？

- 🎯 **考官意图**：考察在物理外键缺失情况下，如何通过只读探查安全验证关联假设。
- 🛡️ **攻防标准应答**：模型必须调用 `run_sql_readonly` 执行探索性验证查询：编写极小样本的 `SELECT t1.col_a, t2.col_b FROM t1, t2 LIMIT 1` 进行真实数据对账，由数据库的真实数据吻合度来验证关联假设，而不是凭空猜测。
- ⚠️ **避坑要点**：不要试图在服务端用同名词启发式硬拼 Join，必须交由探索性 SQL 验证真实数据分布。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 Schema-only 降级能保证基本查询可运行，但在复杂隐式外键库中可能降低初次写对率
- 🛑 系统仅对可观测只读语义工具实施降级，对底层 SQL 执行器不可用则直接熔断


---
