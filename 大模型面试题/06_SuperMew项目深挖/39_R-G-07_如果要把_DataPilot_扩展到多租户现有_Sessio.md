# R-G-07: 如果要把 DataPilot 扩展到多租户，现有 Session、DataSource、Artifact 和密钥边界哪里最先需要重构？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`系统设计, SQL, Sandbox`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 最先重构 DataSource 物理连接与权限隔离，其次重构 Session 租户上下文注入，最后补齐沙箱挂载与密钥 Vault 隔离。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

如果要将 DataPilot 演进为多租户 SaaS，**最先需要重构的是 DataSource 物理数据源连接与权限边界**！当前单租户架构下，数据网关使用的是固定的全局数据库凭据；演进到多租户，必须立即引入动态租户连接池、行级安全控制（RLS）以及逻辑 Schema 隔离，防止租户 A 通过 SQL 探查到租户 B 的表；其次是重构 Session 与 Audit 表结构，全量补上 `tenant_id` 并作为复合主键索引；最后是重构 Docker 沙箱挂载目录与租户专属密钥 KMS 体系。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

将单租户 DataPilot 重构成支持企业级多租户（Multi-Tenant）架构时，四个维度的重构优先级如下：
1. **第 1 优先级：DataSource 物理连接与逻辑隔离（最先重构，安全底线）**：
- 现状缺陷：单租户下全局共享一个数据库连接配置；
- 重构方案：DataSource 必须绑定 tenant_id。每次 SQL 执行时，连接池根据当前租户上下文动态切换只读账号与 schema，或在 SQL AST 解析层强制注入 WHERE tenant_id = 'xxx' 行级安全过滤。

2. **第 2 优先级：Session 与 State 租户上下文注入**：
- 核心代码：LangGraph 状态机与 FastAPI 中间件强绑定租户身份凭证。

```python
from fastapi import Request, HTTPException
from typing import Dict, Any

class TenantContext:
    def __init__(self, tenant_id: str, allowed_db_schemas: list):
        self.tenant_id = tenant_id
        self.allowed_db_schemas = allowed_db_schemas

async def tenant_security_middleware(request: Request, call_next):
    """多租户前置拦截中间件：严格提取租户 ID 并注入请求上下文"""
    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing X-Tenant-ID header")
    
    # 模拟从统一权限服务校验租户有效性及授权库表范围
    request.state.tenant = TenantContext(
        tenant_id=tenant_id,
        allowed_db_schemas=[f"tenant_{tenant_id}"]
    )
    return await call_next(request)
```

3. **第 3 优先级：Docker 沙箱环境与文件系统隔离（Sandbox & Artifacts）**：
- 每个租户启动独立的临时容器实例，或者在沙箱中挂载仅限该租户目录的只读/读写卷（如 /data/tenant_{id}/），防止利用 Python 代码跨租户读取临时生成的图表和数据 CSV。

4. **第 4 优先级：密钥管理（KMS / Vault）与配额审计（Quota Guard）**：
- 各租户的大模型 API Key、数据库密码由 HashiCorp Vault 独立加密托管；
- 实施基于租户维度的 Token 消耗配额限流，防止单一租户并发把集群并发打满。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ P0 最先重构 DataSource：引入动态数据源路由、租户专属只读账号与连接池隔离
- ✔️ P1 数据库全量改造：核心表补齐 tenant_id 复合索引并在 ORM 层注入全局租户拦截器
- ✔️ P2 沙箱与存储隔离：按租户划分物理路径与 S3 隔离，STS 颁发受限临时凭证

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果在 SQL AST 解析器中统一追加 WHERE tenant_id = 'xxx'，遇到复杂的多表 JOIN 或子查询会不会漏掉？

- 🎯 **考官意图**：考察对 AST 树遍历重写算法及行级安全机制的深刻认识。
- 🛡️ **攻防标准应答**：仅靠简单的 AST 遍历重写很容易漏掉子查询或 UNION。生产环境中最稳妥的方案是：1) 数据库原生采用 Schema 隔离（每个租户一个单独的 DB Schema），连接建立后直接 SET search_path = tenant_xxx，从物理引擎底层彻底杜绝跨租户；2) 若单表混合存储，启用 PostgreSQL 原生 Row Level Security (RLS) 策略，通过 SET LOCAL app.current_tenant = 'xxx' 强制生效，避免在应用层拼 SQL。
- ⚠️ **避坑要点**：不要夸大 AST 改写的能力，指出数据库原生 Schema 隔离或 RLS 才是工业界最稳健方案。

###### 🎯 追问对决：多租户沙箱如何防止某个租户占用过多宿主机内存导致其他租户 OOM？

- 🎯 **考官意图**：考察容器资源隔离与 Cgroups 限制。
- 🛡️ **攻防标准应答**：通过 Docker API 创建容器时，严格传入 Cgroups 限制参数：-m 512m --cpus=1.0 --pids-limit=64。当单个租户代码发生内存泄露时，只会被 OOM-killer 杀死该租户的独立容器，绝对不会波及宿主机及其他租户的沙箱容器。
- ⚠️ **避坑要点**：必须明确给出具体的 Docker/Cgroups 资源隔离参数。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 多租户改造是一项系统级重构，当前单机代码库优先聚焦于单租户受控安全与审计闭环
- 🛑 行级数据隔离需数据库本身支持或由代理层精准重写，需防范注入绕过


---
