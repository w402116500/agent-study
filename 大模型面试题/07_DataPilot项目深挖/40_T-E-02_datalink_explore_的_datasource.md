# T-E-02: `datalink_explore` 的 `datasource_id`、`graph_version`、`focus`、`max_nodes` 如何保证版本和范围正确？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`DataLink, 接口参数, 版本控制`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> datalink_explore 依靠版本快照对齐 Schema，focus 锚定检索起点，max_nodes 强控 Token 预算。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

`datalink_explore` 入参中，`datasource_id` 锁定物理数据源；`graph_version` 绑定该库当前 DDL 快照版本，版本不匹配直接阻断；`focus` 作为局部拓扑检索的种子节点（表名或字段名）；`max_nodes`（默认 15）设置硬上限，配合局部 BFS 截断，确保返回的子图和 Join 路径在 Token 预算和注意力范围内。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

datalink_explore 四参数的精确约束与版本漂移防御：
1. **四大参数职责与防御红线**：
- `datasource_id`：租户数据源隔离界限，严禁跨库混查；
- `graph_version`：图谱快照版本号，强制要求与当前 Run 启动时绑定的快照版本完全一致，防止“图谱动态更新导致前后拓扑漂移”；
- `focus`：探查的实体或概念焦点，通常为表名或业务概念（如 `orders`, `refund`）；
- `max_nodes`：控制返回的局部子图规模（默认 15，上限 30），防止拓扑爆炸撑爆大模型 Context。

2. **核心代码：参数校验与版本守卫器**：

```python
from pydantic import BaseModel, Field, validator

class DatalinkExploreRequest(BaseModel):
    datasource_id: str
    graph_version: str
    focus: str
    max_nodes: int = Field(default=15, ge=1, le=30)

    @validator('max_nodes')
    def enforce_strict_node_limit(cls, v):
        if v > 30:
            return 30 # 强行截断，防止子图过大
        return v

def validate_and_execute_datalink(req: DatalinkExploreRequest, run_context) -> dict:
    # 核心安全校验：断言模型传入的 graph_version 是否匹配本 Run 冻结版本
    if req.graph_version != run_context.graph_version:
        raise ValueError(
            f"版本漂移拦截: 请求版本 {req.graph_version} 与当前运行冻结版本 "
            f"{run_context.graph_version} 不一致，拒绝跨版本探查"
        )
    return execute_graph_search(req)
```

3. **运行指标与异常处理**：
- 节点数限制在 15~30 个节点，对应生成的 JSON 文本量在 800~1500 字符内，精准提供关联外键拓扑，避免向 Prompt 倾倒整个企业级大图。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ graph_version 强制绑定元数据快照指纹，杜绝 DDL 演变导致的语义图谱与物理表脱节
- ✔️ focus 限制以种子实体为核心展开局部图搜索，消除跨库漫游与注意力漂移
- ✔️ max_nodes 设置硬边界并服务端截断，严格保护 LLM 上下文窗口与推理耗时

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果模型传入的 focus 实体在图谱中完全不存在（例如模型臆造了一个不存在的表），工具如何响应？

- 🎯 **考官意图**：考察空结果优雅降级与模型提示反馈。
- 🛡️ **攻防标准应答**：返回结构化空响应：`{"nodes": [], "suggested_entities": ["相似实体1", "相似实体2"], "status": "NOT_FOUND"}`。明确告知大模型未找到该实体，并附带编辑距离最接近的有效表名建议，引导模型在下一轮校准实体名称，严禁直接抛 500 系统异常。
- ⚠️ **避坑要点**：不要直接抛出系统级未捕获异常，应当以友好的领域结构体通知模型修正。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 max_nodes 仅控制当前工具调用的子图规模，不代表全库关联图的实际容量
- 🛑 focus 仅支持当前数据源内的已知实体名，不支持跨数据源的联合图遍历


---
