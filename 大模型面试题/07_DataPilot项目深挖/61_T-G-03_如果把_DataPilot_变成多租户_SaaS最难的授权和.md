# T-G-03: 如果把 DataPilot 变成多租户 SaaS，最难的授权和隔离问题是什么？

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`多租户, SaaS, 权限隔离, 安全架构`
- **可信级别**：架构演进 / 安全设计

> 💡 **一句话速记结论**：
> 最难的是动态计算环境与沙箱运行时的租户逃逸隔离，以及跨会话状态下凭据与上下文污染防范。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

如果将 DataPilot 演进为多租户 SaaS，最难的绝不仅是数据库加 `tenant_id`，而是动态代码执行沙箱的隔离与数据连接凭据的生命周期防护。多租户下，不可信的 Python 代码在共享宿主机或容器集群中运行，必须彻底防御 CPU/内存抢占、宿主内核逃逸与容器网络嗅探；同时，模型在分析跨租户数据时，Prompt 上下文、会话缓存（Redis）以及临时持久化快照稍有不慎就会发生横向越权泄漏，必须做到从 API 鉴权、沙箱微虚拟机隔离到只读出口审计的全链路行级闭环。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

DataPilot 改造为多租户 SaaS 时的授权与隔离痛点及解决方案：
1. **多租户最具挑战的两大核心痛点**：
- **痛点 1：异构数据源凭据安全托管与动态委派**：
  不同租户自带 AWS RDS、私有 PostgreSQL 等。系统既不能在代码中硬编码，又不能让 Worker 节点常驻明文凭据，且必须在连接时实现细粒度按需鉴权；
- **痛点 2：大模型生成的 SQL 隐式跨租户越权（Cross-Tenant Data Leakage）**：
  若租户共享同一张业务大宽表（如 `orders` 表通过 `tenant_id` 区分），大模型写出的 SQL 如果偶然漏写了 `WHERE tenant_id = 'xxx'`，将直接爆出其他企业的绝密数据。

2. **核心代码：强制行级安全注入与动态凭据网关**：

```python
from sqlglot import parse_one, exp

class TenantIsolationEnforcer:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    def inject_mandatory_row_security(self, raw_sql: str) -> str:
        """
        在 AST 语法树层面对所有涉及租户表的查询，
        无条件强行注入 tenant_id = '...' 过滤条件
        """
        expression = parse_one(raw_sql, read="postgres")
        
        # 构造强制租户过滤谓词
        tenant_predicate = exp.EQ(
            this=exp.Column(this="tenant_id"),
            expression=exp.Literal.string(self.tenant_id)
        )
        
        # 将谓词合入主查询的 WHERE 子句中
        where_clause = expression.args.get("where")
        if where_clause:
            expression.set("where", exp.And(this=where_clause.this, expression=tenant_predicate))
        else:
            expression.set("where", exp.Where(this=tenant_predicate))
            
        return expression.sql(dialect="postgres")
```

3. **双重保险**：
- 在应用层做 AST 强行改写注入；在底层数据库物理层面开启 **PostgreSQL Row Level Security (RLS)**，为每个会话设置 `SET LOCAL app.current_tenant = 'xxx'`，实现数据库内核级的硬隔离，彻底杜绝数据穿透。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 最大挑战是计算沙箱逃逸与共享内核风险，必须从 Docker 升级至 gVisor 或 Firecracker 微虚拟机
- ✔️ 动态数据源凭据绝不注入沙箱，采用短命只读 Token 或宿主安全中继代理隔离
- ✔️ 存储采用 PostgreSQL RLS 与命名空间分片，缓存与向量检索强绑定 tenant_id 硬隔离

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果租户要求数据库完全物理隔离（每个租户独立的数据库实例），架构上如何动态路由？

- 🎯 **考官意图**：考察多租户架构设计（Schema 隔离 vs 物理库隔离）与动态数据源路由。
- 🛡️ **攻防标准应答**：采用【租户动态连接池路由网关（Dynamic Routing DataSource Pool）】：网关基于 JWT 中的 `tenant_id` 查找元数据注册中心，动态获取对应物理库的只读连接串，通过 LRU 缓存租户连接池，实现物理实例级的完全物理封锁与零交叉。
- ⚠️ **避坑要点**：不要在应用启动时一次性初始化所有租户的全部连接，租户量膨胀后会导致数据库连接数瞬间被撑爆。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 当前 DataPilot 仅支持单机部署与企业内部单租户环境，默认 Docker 宿主隔离
- 🛑 多租户 SaaS 化会引入分布式集群调度（K8s CRD/KubeVirt）并推高整体基础设施运维成本


---
