# R-P2-03: 说“自建 MCP 服务”；DataLink 为什么独立部署，哪些能力不放进主后端？

- **归属项目**：`DataPilot` | **题目类型**：`证据核验题` | **难度等级**：`进阶` | **核心主题**：`MCP, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> DataLink 独立部署 FastMCP 解耦元数据图谱探索与计算隔离，主后端绝不引入重量级图引擎和全量 DDL。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

DataLink 采用 FastMCP 协议独立为微服务部署，核心原因是元数据图谱服务与 Agent 主后端的职责边界截然不同：主后端负责业务会话、LangGraph 调度和 SSE 推送；而 DataLink 负责维护包含数百张表及其外键关联的语义关系图。如果把图谱搜索和全量 DDL 揉进主后端，不仅会污染核心业务依赖，更会导致每次多租户扩容时图谱内存膨胀。通过 FastMCP 暴露唯一的 `datalink_explore` 工具，主后端按需传入中心表和深度获取局域拓扑，实现优雅解耦与安全防爆。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

自建 FastMCP DataLink 服务的设计考量与架构边界如下：
1. **为什么独立部署 FastMCP DataLink 而不放进主后端**：
- **解耦拓扑检索与图计算引擎**：DataLink 底层维护了企业数据仓库 200+ 张数据表、3500+ 个字段的拓扑关系网络（NetworkX / Neo4j），包含语义同义词与多跳关联。主后端是基于 FastAPI + LangGraph 的无状态推理引擎，如果把庞大的图内存结构混杂进来，会导致主服务启动缓慢且不可水平扩容；
- **物理隔离全量 DDL 泄露风险**：大模型若直连主后端 DB 获取全量 DDL，极易在 System Prompt 中泄露涉及内部敏感系统（如薪资表 `emp_salary`、审计密文表 `sys_audit_secret`）的敏感元数据。DataLink 独立部署后，充当只读语义发现网关，对外只暴露脱敏和授权后的局部子图。

2. **DataLink 对外开放的 MCP 工具契约（Tool Contract）**：
- `datalink_explore(focus_tables: List[str], max_hops: int = 2)`：输入当前关心的核心表名，仅返回 2 跳以内的关联路径与业务注释；
- `datalink_search_columns(keyword: str)`：按业务语义（如“GMV”、“留存率”）反向定位候选表与计算公式。

3. **核心代码：FastMCP 独立服务端与语义图谱裁剪实现**：
```python
from mcp.server.fastmcp import FastMCP
from typing import List, Dict
import networkx as nx

# 创建独立 FastMCP 语义发现微服务
mcp = FastMCP("DataPilot-DataLink-Service")

# 初始化内存数据仓库拓扑图谱（节点为数据表，边为外键关系与业务口径链路）
metadata_graph = nx.DiGraph()
metadata_graph.add_edge("dim_user", "fact_orders", relation="user_id", business_desc="用户下的订单")
metadata_graph.add_edge("fact_orders", "fact_order_items", relation="order_id", business_desc="订单明细")
metadata_graph.add_edge("dim_products", "fact_order_items", relation="product_id", business_desc="商品销售记录")

@mcp.tool()
def datalink_explore(focus_tables: List[str], max_hops: int = 2) -> Dict[str, Any]:
    """受控语义探查工具：仅暴露指定表特定跳数内的局部拓扑结构，防止 DDL 爆显存与泄露"""
    subgraph_nodes = set(focus_tables)
    for table in focus_tables:
        if table in metadata_graph:
            # 获取受控跳数以内的邻居节点
            lengths = nx.single_source_shortest_path_length(metadata_graph, table, cutoff=max_hops)
            subgraph_nodes.update(lengths.keys())
            
    # 提取局部子图详情（带字段脱敏与白名单过滤）
    result_tables = []
    for node in subgraph_nodes:
        result_tables.append({
            "table_name": node,
            "columns": get_table_schema_safe(node), # 过滤掉包含 password/salary 的敏感字段
            "relations": [e for e in metadata_graph.edges(node, data=True)]
        })
    return {"schema_version": "v2024.11", "tables": result_tables}
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ DataLink 作为独立 FastMCP 服务解耦图谱检索与 Agent 业务主后端
- ✔️ 杜绝全量 DDL 塞入主后端与 LLM 上下文，仅返回中心表局部拓扑
- ✔️ 服务宕机时自动降级到传统 Schema 模式并打可观察性标记

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果 DataLink 独立微服务宕机或出现网络超时，主 Agent 会不会直接报 500 崩溃？

- 🎯 **考官意图**：考察微服务架构下的高可用、降级保护与容错机制（Graceful Degradation）。
- 🛡️ **攻防标准应答**：绝对不会。我们在主后端设计了优雅降级机制（Graceful Fallback）：Agent 发现 DataLink 连接异常或超时（3s 熔断）后，立即切换至本地轻量级 Schema 缓存（存放在 Redis 中的核心 10 张基础表骨架 DDL）；同时向上下文注入 Warning 标记：'语义图谱不可用，已切换至基础表模式'，Agent 继续凭借基础表完成核心 SQL 编写，保证主流程不中断。
- ⚠️ **避坑要点**：不要只说'重试三次'，超时不处理会拖垮主事件循环，必须强调超时熔断与切换本地备用元数据缓存。

###### 🎯 追问对决：为什么用 FastMCP 协议而不是通用的 gRPC 或普通 HTTP RESTful 接口？

- 🎯 **考官意图**：考察对 Model Context Protocol (MCP) 标准的技术洞察与生态优势理解。
- 🛡️ **攻防标准应答**：选用 FastMCP 有三大核心优势：1) 协议原生适配：MCP 是专门为大模型工具交互定制的标准协议，原生支持能力发现（Capability Discovery）、工具自描述（JSON Schema 自动推导）与动态资源暴露；2) 客户端解耦：Agent 无需为每个微服务手动编写 Client 适配器，直接通过标准 MCP Client 即可接入任意数据源；3) 方便未来接入 Claude Desktop 或外部 Agent 主机进行跨系统协作。
- ⚠️ **避坑要点**：必须讲出 MCP 在 Agent 工具发现、标准化 JSON Schema 生成和跨系统标准化生态上的不可替代性。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 DataLink 仅提供语义拓扑参考，不替主后端生成或执行具体 SQL 语句
- 🛑 降级为普通 Schema 模式后，多表关联复杂分析的准确率会有所下降


---
