# R-P3-12: 提到 Claim/Evidence；SQL、Python、DataLink 证据各自能支撑什么，不允许支撑什么？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`Agent, SQL, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> SQL 证据支撑客观数值事实，Python 证据支撑计算衍生与图表，DataLink 仅支撑拓扑与口径说明；三者皆不可互相越权支撑。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

在严谨的企业分析中，我们对 Claim（结论论点）与 Evidence（支撑证据）的绑定边界设立了铁律：**SQL 证据**只能支撑‘直接从数据库聚合查出的原生客观数值与明细事实’；**Python 证据**只能支撑‘多步复杂统计模型计算出的衍生指标及生成的图表产物’；而 **DataLink 证据**只能支撑‘表结构拓扑关联性与业务口径定义’。绝不允许用 DataLink 证明数值存在，也不允许用 SQL 假装证明了趋势拟合，每条业务结论必须精准锚定在其合法证据源上。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

Claim / Evidence 契约与 SQL、Python、DataLink 证据支撑边界：
1. **三大证据来源的正交支撑边界**：
- **SQL 证据**：只支撑“直接查询出的聚合值或原始数据”，如“2024Q3退货订单共计 1,420 笔”；绝不允许支撑未经计算的宏观归因推论；
- **Python 证据**：支撑“数学统计、趋势回归、方差分析与可视化图表”，如“退货率与促销折扣呈显著正相关（r=0.82）”；
- **DataLink 证据**：仅支撑“字段含义、业务口径说明与实体关系拓扑”，绝不能充当数值论据。

2. **核心代码：FinalMarkdownPayload 证据绑定契约验证（含逐行注释）**：
```python
from pydantic import BaseModel, Field, validator
from typing import List, Literal

class ClaimEvidenceBinding(BaseModel):
    claim_id: str = Field(..., description="论点编号，如 C-01")
    text: str = Field(..., description="回答中的具体论断文字")
    evidence_type: Literal["SQL", "PYTHON", "DATALINK"] = Field(..., description="证据类型")
    artifact_id: str = Field(..., description="对应的审计记录 ID 或图表文件 ID")

class FinalReportPayload(BaseModel):
    summary: str = Field(..., description="分析总结报告正文")
    claims: List[ClaimEvidenceBinding] = Field(..., description="声明与证据绑定列表")

    @validator("claims")
    def validate_evidence_integrity(cls, claims):
        # 校验：任何声明必须绑定至少一个有效证据 ID
        for c in claims:
            if not c.artifact_id:
                raise ValueError(f"Claim {c.claim_id} lacks concrete evidence backing!")
        return claims
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ SQL 证据支撑原生离散数据与基础聚合，不能支撑统计推断
- ✔️ Python 证据支撑高级计算模型与图表产物，不能脱离输入快照凭空产生
- ✔️ DataLink 仅能支撑元数据关联与口径定义，绝对不允许支撑任何数值性结论

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果大模型得出了一个宏观推论，既包含数值又包含图表，如何关联复合证据？

- 🎯 **考官意图**：考察复杂论点对复合型证据（Composite Evidence）的绑定建模。
- 🛡️ **攻防标准应答**：在 ClaimEvidenceBinding 中支持绑定多个 `artifact_ids`，例如 Claim-01 可同时关联一个 SQL 聚合查询的 audit_id 和一个 Python 趋势图的 artifact_id，在报告中渲染为复合角标 `[SQL:42, CHART:07]`，支持用户双向追溯。
- ⚠️ **避坑要点**：不能把复合推论拆散成碎片让证据脱节，必须通过统一的模型支持 1 对 N 证据关联。

###### 🎯 追问对决：当 SQL 查出的结果与 Python 计算出的结果存在细微舍入误差时，以谁为准？

- 🎯 **考官意图**：考察不同数据计算引擎的精度信任基线与对齐标准。
- 🛡️ **攻防标准应答**：以数据库 SQL 的原始聚合为准。Python 作为下游绘图与统计工具，由于浮点数表示（如 IEEE 754 精度）可能会引入微小漂移；所有财务级精确数值严格以数据库 DECIMAL / NUMERIC 字段的 SQL 结果为黄金基准。
- ⚠️ **避坑要点**：千万不要说'以 Python 为准因为 Python 算得更灵活'，数据库原生定点数才是企业报表的唯一金标准。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 证据绑定机制约束的是大模型结论的证据链合法性，非业务本身的商业决策真伪
- 🛑 未挂载任何证据的纯文字段落，在合规审计中被降级标记为‘模型经验推测’


---
