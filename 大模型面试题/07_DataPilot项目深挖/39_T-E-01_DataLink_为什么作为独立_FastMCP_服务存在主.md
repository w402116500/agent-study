# T-E-01: DataLink 为什么作为独立 FastMCP 服务存在？主后端通过什么传输调用，服务只暴露哪个工具？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`DataLink, FastMCP, 架构设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> DataLink 作为独立 FastMCP 服务解耦图计算与主后端，仅暴露单一受控工具 datalink_explore。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

DataLink 将高计算开销的语义图谱构建、关联发现与 NetworkX 拓扑检索解耦为主后端之外的独立 FastMCP 微服务。主后端通过标准 stdio / SSE 传输协议与之通信。为防止 Prompt 注入与无约束的图查询，服务严格只暴露一个标准化工具 datalink_explore，屏蔽底层图引擎细节，仅返回受控的局部语义子图与关联路径。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

DataLink 独立 FastMCP 服务架构、传输契约与单一工具暴露原则：
1. **独立服务架构解耦诉求**：
- 知识图谱运算（Neo4j/NetworkX 拓扑最短路径分析、实体解析、同义词聚类）具有典型的计算密集与重内存特征，若与主 Web 后端混部，突发图谱分析将造成主 Web 接口剧烈 GC 抖动。
- 采用 FastMCP 标准独立微服务化：主后端与 DataLink 服务之间通过标准 **stdio（本地管道）或 HTTP SSE/JSON-RPC** 进行进程间协议交互。
- 单一工具暴露原则：服务**仅暴露唯一工具 `datalink_explore`**，对大模型隐藏底层 Neo4j Cypher 注入与复杂的子图算法，保持最简协议交互面。

2. **核心代码：FastMCP 单一工具服务端实现**：

```python
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import List, Dict, Any

# 初始化独立的 FastMCP 服务实例
mcp = FastMCP("DataLink-KnowledgeGraph-Service")

class ExploreArgs(BaseModel):
    datasource_id: str = Field(..., description="目标数据源隔离ID")
    graph_version: str = Field(..., description="绑定的图谱快照版本")
    focus: str = Field(..., description="探索的核心实体，如 'customer_refund'")
    max_nodes: int = Field(default=15, le=30, description="最大扩展节点数")

@mcp.tool(name="datalink_explore", description="探查业务拓扑、表关联关系与推荐 Join 路径")
def datalink_explore(args: ExploreArgs) -> Dict[str, Any]:
    """唯一暴露给 Agent 的探查工具，严禁暴露原始 Cypher 执行接口"""
    # 1. 校验版本有效性
    # 2. 从图数据库提取围绕 focus 实体的局部子图与关联外键路径
    subgraph = {
        "focus": args.focus,
        "nodes": [{"id": "orders", "type": "FactTable"}, {"id": "refunds", "type": "FactTable"}],
        "join_paths": [
            "orders.order_id = refunds.order_id (1:N 关联，通过订单号核算退款)"
        ],
        "semantic_hints": "refunds 表记录明细退款，应使用 SUM(refund_amount) 统计损失"
    }
    return subgraph

if __name__ == "__main__":
    mcp.run()
```

3. **安全与工程收益**：
- 故障彻底隔离：即使 DataLink 进程发生 OOM 崩溃，主后端只需做工具超时降级，主流程依然能凭借基础 SQL 元数据稳健运行。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ FastMCP 独立服务解耦了重型图算法计算与主 API 进程，支持作为企业通用数据资产复用
- ✔️ 通信基于标准 stdio 或 SSE 传输，请求生命周期具备统一上下文与 Trace 追踪
- ✔️ 遵循最小权限原则严格只暴露 datalink_explore 单一工具，阻断无约束图遍历与越权注入

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：为什么不直接让大模型编写 Cypher 语句查询 Neo4j，而是封装为 datalink_explore 工具？

- 🎯 **考官意图**：考察防注入与模型能力边界控制。
- 🛡️ **攻防标准应答**：原因有二：1) 编写高质量 Cypher 对大模型要求过高，极易产生语法幻觉与笛卡尔积慢查询；2) 暴露原始 Cypher 面临严重的图数据库越权注入风险。通过特定工具封装，将输入参数收敛为 focus 实体和版本，从根本上杜绝了恶意注入与慢查询引发的服务雪崩。
- ⚠️ **避坑要点**：不要回答让模型直接写原生图查询语言，这违背了企业级安全隔离原则。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 DataLink 仅维护元数据拓扑与脱敏枚举分布，不承载真实业务数据的行级存储
- 🛑 图谱更新是异步离线/近线触发的快照任务，不支持事务级实时图更新


---
