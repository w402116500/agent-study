# R-P3-10: 提到 FastMCP；`datalink_explore` 的版本、datasource 和 `max_nodes` 为什么都要进契约？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`MCP, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 版本确保图谱结构兼容，datasource 实现租户多数据源隔离，max_nodes 硬性防范拓扑子图打爆大模型上下文。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

在自建 FastMCP 的 `datalink_explore` 工具设计中，这三个参数是核心契约的压舱石：`version`（版本号）保证了数据仓库在增减字段、更新关系时，Agent 使用的是对应快照的图谱，避免脏读；`datasource`（数据源标识）实现了物理多租户与多业务库的绝对隔离；而 `max_nodes`（默认 10）则是至关重要的**上下文防爆硬约束**，强制图遍历算法只返回最核心的局域拓扑节点，防止在大宽表关联时一下子吐出上百张表直接挤爆大模型上下文窗口。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

FastMCP `datalink_explore` 的参数契约与拓扑控制：
1. **三大核心参数的架构意图**：
- `schema_version`：确保拓扑与快照版本强一致，防止元数据在多轮对话中发生漂移；
- `datasource_id`：多租户物理数据源隔离边界；
- `max_nodes`：硬性上限（默认 15，最大 30），防止大模型一次拉出包含上百张表的庞大拓扑图导致上下文瞬间爆仓。

2. **核心代码：FastMCP 拓扑探查工具定义（含逐行注释）**：
```python
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import List, Dict

mcp = FastMCP("DataLinkService")

class ExploreDataLinkInput(BaseModel):
    schema_version: str = Field(..., description="冻结的元数据快照版本号")
    datasource_id: str = Field(..., description="目标数据源唯一标识符")
    focus_tables: List[str] = Field(..., description="探查的核心表名称列表")
    max_nodes: int = Field(15, ge=1, le=30, description="返回子图的最大节点数，防止打爆上下文")

@mcp.tool()
async def datalink_explore(args: ExploreDataLinkInput) -> Dict[str, Any]:
    """受控探查关系拓扑图谱，仅返回紧密连通子图"""
    # 1. 校验版本是否与当前激活的数据源一致
    if not await verify_schema_version(args.datasource_id, args.schema_version):
        return {"error": "Schema version mismatch. Snapshot refreshed required."}

    # 2. 根据 focus_tables 从拓扑图提取 BFS 1~2 度关联实体
    subgraph = extract_subgraph(
        datasource_id=args.datasource_id,
        seeds=args.focus_tables,
        node_limit=args.max_nodes
    )
    return {"nodes": subgraph.nodes, "edges": subgraph.edges, "node_count": len(subgraph.nodes)}
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ version 参数绑定图谱快照，避免数仓元数据热变更导致同一 Run 内前后不一致
- ✔️ datasource 实现跨业务库与多租户的图命名空间绝对隔离
- ✔️ max_nodes 硬性将返回子图节点控制在 10 个以内，杜绝图扩散打爆 LLM 上下文

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果 10 个节点没有包含模型真正需要的连通表，模型如何递进探索？

- 🎯 **考官意图**：考察智能体基于图谱的递进探索（Iterative Graph Walk）能力。
- 🛡️ **攻防标准应答**：大模型在第一轮探查中若发现缺少目标表，可基于已返回节点中的外键边发起第二轮探查，将新表名作为新的 `focus_tables` 传入，像雷达扫描一样逐步向外延伸探索，直至找到打通链路的关键桥接表。
- ⚠️ **避坑要点**：不要说'直接把 max_nodes 调到 500'，一次性拉取整个图谱不仅打爆上下文，还会让模型迷失在海量无关表之间。

###### 🎯 追问对决：DataLink 底层的图谱数据是保存在内存中还是保存在专用图数据库（如 Neo4j）中？

- 🎯 **考官意图**：考察企业数据规模下的架构适度设计与选型依据。
- 🛡️ **攻防标准应答**：在百张表规模的企业数据分析场景下，DataLink 图谱保存在 Redis 内存结构中，并构建了基于 NetworkX 的轻量图索引，内存占用不足 50MB，拓扑遍历仅需 2~5ms；无需引入庞大厚重的 Neo4j 图数据库，极大地降低了系统运维复杂度。
- ⚠️ **避坑要点**：不要盲目炫耀引入了 Neo4j，对于大多数企业千表以内的数据分析，轻量内存储存才是性价比最高的方案。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 DataLink 仅返回静态表拓扑结构与 Join 键，不返回表内真实的行级业务数据
- 🛑 max_nodes 超过 20 时会被服务端接口拒绝，强制模型必须分批递进探索


---
