# T-C-05: `run_sql_readonly`、`run_python`、`explore_datalink` 的参数 Schema 和可用条件分别是什么？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`Agent, 工具契约, Schema设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 严格定义三类工具参数 Schema：SQL 绑只读，Python 显式声明输出，DataLink 依赖图谱版本。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

`run_sql_readonly` 接收 `{sql: str}`，在计划物化后可用；`run_python` 接收 `{script: str, output_paths: list[str], purpose: str}`，必须显式声明生成的产物相对路径，需 Python 依赖时可用；`explore_datalink` 接收 `{query: str, focus: str, max_nodes: int}`，仅在当前 Run 快照具备有效图谱版本（`datalink_graph_version`）时才向模型暴露。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

三核心工具的参数 Schema 与前置可用条件矩阵：
1. **工具矩阵总览**：
- `run_sql_readonly`：只读 SQL 查询器，用于拉取聚合指标数据。
- `run_python`：沙箱隔离的代码执行器，用于数值计算、统计建模与 Matplotlib 图表渲染。
- `explore_datalink`：基于 FastMCP 的图谱探查工具，用于获取实体拓扑与关联 Join Path。

2. **核心代码：Pydantic 参数 Schema 与前置断言校验**：

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class RunSqlReadonlySchema(BaseModel):
    sql: str = Field(..., description="合法的 ANSI SQL SELECT 查询语句，严禁 DDL/DML 与多语句")
    max_rows: Optional[int] = Field(default=100, le=1000, description="最大返回行数，绝对上限 1000")
    datasource_id: str = Field(..., description="绑定的数据源实例唯一标识")

class RunPythonSchema(BaseModel):
    code: str = Field(..., description="待执行的 Python 脚本，仅允许基础数学库与 Matplotlib")
    declared_artifacts: List[str] = Field(
        default_factory=list, 
        description="本脚本预期生成的产物文件名列表（如 ['chart.png']），未声明的写入将被隔离"
    )

class ExploreDatalinkSchema(BaseModel):
    focus_entity: str = Field(..., description="探查的核心业务实体，如 'orders'")
    max_depth: int = Field(default=2, le=3, description="图谱关联深度，最大支持 3 层跳跃")
```

3. **可用条件（Pre-conditions）生产约束**：
- `run_sql_readonly`：必须在合法租户上下文，且当前会话具备已核准的数据源权限；
- `run_python`：必须在本 Run 内部已经成功产出了 SQL 查询数据集，严禁空上下文运行；
- `explore_datalink`：只在 Discovery 探索阶段开放，一旦进入 Final Answer 生成阶段立即被卸载，防止模型在最终答案中反复调用图谱产生抖动。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ run_sql_readonly 仅接收纯 SQL，强绑定只读数据源，前置阻断一切非只读属性
- ✔️ run_python 强制声明 output_paths 相对路径清单，杜绝随意写入未声明文件
- ✔️ explore_datalink 仅在图谱健康且持有有效版本时动态挂载，服务挂掉时透明降级

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：为什么不允许模型在 run_python 中直接执行数据库查询代码（如 import psycopg2）？

- 🎯 **考官意图**：考察网络隔离与架构单一职责原则。
- 🛡️ **攻防标准应答**：因为 Python 执行容器被施加了 `--network=none` 纯物理网络隔离，杜绝数据外发与反弹 Shell；如果允许其直连数据库，不仅绕过了 sqlglot 的 AST 只读审计与 LIMIT 防线，还会引发沙箱直连内网的重大安全穿透事故。
- ⚠️ **避坑要点**：切勿说为了方便可以开放只读连接给沙箱，容器网络绝对不能连通内网数据库。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 模型不能通过工具参数篡改执行环境（如不能传入自定义环境变量或 pip install 参数）
- 🛑 工具定义全部遵循 JSON Schema 规范，通过 LangChain 原生 bind_tools 注入大模型


---
