# E-07: MCP Host、Client、Server 各自负责什么？MCP 与普通 Function Calling 的边界是什么？

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`MCP协议, 架构边界, Host-Client-Server, 标准化`
- **可信级别**：项目事实 / 协议标准

> 💡 **一句话速记结论**：
> Host 提供运行上下文与交互UI，Client 负责安全路由与握手协议，Server 是无状态的标准化能力提供方。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

MCP（Model Context Protocol）将传统的单体工具调用彻底解耦为三层：Host 是承载模型与用户交互的应用主体（如 Claude Desktop 或我们的 DataPilot 应用）；Client 运行在 Host 内，负责与各个 Server 建立传输连接、处理能力协商与安全鉴权；Server 是独立的工具或数据服务，暴露标准化 Tools、Resources 和 Prompts。与普通 Function Calling 相比，传统 FC 是硬编码在单个业务服务里的私有字典，而 MCP 是一种跨语言、进程隔离、可动态热插拔的开放 RPC 协议，实现了工具的即插即用和生态复用。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

MCP（Model Context Protocol）Host、Client、Server 的权责划分与通用 Function Calling 边界：
1. **MCP 核心架构三大角色的物理职责**：
- **Host（宿主应用程序，如 Claude Desktop、Cursor、DataPilot Web）**：
  - 职责：提供人机交互界面，发起 LLM 推理请求，管理用户身份认证、全局会话生命周期与权限授权审批弹窗；
- **Client（MCP 客户端协议驱动器）**：
  - 职责：维护与各 MCP Server 的协议连接（stdio / SSE / HTTP），完成能力握手协商（Capabilities Discovery），安全路由工具调用与资源映射；
- **Server（MCP 协议服务端，如 modular-rag-mcp-server）**：
  - 职责：专职无状态的能力提供方，声明暴露的标准工具（Tools）、外部只读资源（Resources）与提示词模板（Prompts），不关心是哪个模型在调用。

2. **核心代码：MCP Server 标准能力暴露与协议分发**：

```python
from mcp.server.fastmcp import FastMCP
from typing import Dict, Any

# 创建标准 MCP 服务端实例，命名空间清晰
mcp = FastMCP("financial-analysis-mcp")

# 1. 声明对外暴露的标准工具能力
@mcp.tool(
    name="retrieve_financial_filings",
    description="在向量知识库中基于混合检索查询上市公司财报原始文本"
)
async def retrieve_financial_filings(ticker: str, year: int, query: str) -> Dict[str, Any]:
    # 纯能力提供：只负责核心业务逻辑与规范化输出，不绑定任何特定 LLM SDK
    results = await run_hybrid_search(ticker=ticker, year=year, query=query)
    return {"status": "SUCCESS", "chunks": results}

# 2. 声明对外暴露的只读安全资源
@mcp.resource("schema://database/tables")
def get_database_schema() -> str:
    # 允许 Client 主动读取环境上下文，无需通过大模型推理触发
    return "TABLE orders(id INT, amount DECIMAL, created_at TIMESTAMP);"
```

3. **MCP 与传统普通 Function Calling 的本质区别**：
- **协议解耦度**：Function Calling 是单一厂商（如 OpenAI、智谱）私有的 API JSON 规范，工具代码必须强耦合写死在业务后端的 Prompt 或入参字典中；MCP 是**跨模型、跨应用的标准开放协议**，一个 MCP Server 写一次，即可同时挂载到 Claude、OpenAI、Cursor 或本地私有模型中；
- **能力维度不仅限于工具**：传统 Function Calling 只有“函数调用”一种被动交互；MCP 额外提供了 **Resources（主动数据源挂载）** 和 **Prompts（服务端标准交互模板）**，具备完善的客户端权限协商机制。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ Host 掌握用户交互与上下文决策权，Client 负责协议协商与连接路由，Server 专注于标准化能力供给
- ✔️ 普通 FC 是私有硬编码的同进程字典，MCP 是跨语言、跨进程、标准化的开放 JSON-RPC 规范
- ✔️ MCP 实现了生态级别的工具即插即用，并天然具备微服务级别的进程隔离与安全沙箱特性

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：在本地通过 stdio 运行的 MCP Server 与通过远程 SSE 运行的 Server，在并发吞吐与连接维持上有何本质差异？

- 🎯 **考官意图**：考察 MCP 传输层协议（stdio vs SSE）的选型认知与并发考量。
- 🛡️ **攻防标准应答**：stdio 是通过操作系统标准输入输出管道通信，专为本地宿主与独立子进程设计，延迟极低（微秒级）、安全性极高（无公网端口暴露风险），但属于单宿主独占，无法跨主机共享；远程 SSE（Server-Sent Events）基于 HTTP 长连接，适合企业集中化微服务部署，支持多客户端并发连接与分布式部署，但需要额外处理网络鉴权、反向代理长连接超时与心跳保活。
- ⚠️ **避坑要点**：不要把本地桌面工具的 stdio 部署直接套用到云端多租户微服务，云端多租户必须选 HTTP/SSE 模式。

###### 🎯 追问对决：如果一个第三方的 MCP Server 恶意暴露了超过 50 个工具导致上下文爆仓，Client 层该如何做工具动态检索与按需裁剪？

- 🎯 **考官意图**：考察海量工具场景下的动态工具检索与挂载（Tool RAG / Dynamic Tool Selection）。
- 🛡️ **攻防标准应答**：实施【工具语义索引与动态注入（Tool RAG）】：Client 在初始化时拉取 Server 的 50 个工具描述，但在首轮向大模型发起请求时，并不把这 50 个工具的 JSON 全量塞进上下文；而是把工具的名字和 description 向量化存入轻量向量库。根据当前用户的用户 Query 实时检索相关度最高的 Top-4 工具动态组装进 Tools 列表，其余工具被隐藏，将上下文占用压缩 90% 以上并大幅提升模型意图识别率。
- ⚠️ **避坑要点**：不要试图一次性把 50 个工具的复杂 JSON 全部塞进 System Prompt，模型极易产生注意力涣散和幻觉混淆。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 MCP 协议增加了跨进程 IPC/RPC 的微小网络开销（通常在几毫秒级）
- 🛑 当前 DataPilot 将 DuckDB 和 SQLite 封装为受控的专用内部工具，同时支持标准化 MCP 接口扩展


---
