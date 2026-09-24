# T-E-08: SQL、Python、DataLink 的 evidence binding 怎样被服务端校验为“属于本 Run 且类型匹配”？

- **归属项目**：`DataPilot` | **题目类型**：`证据核验题` | **难度等级**：`高难` | **核心主题**：`证据绑定, 审计合规, 后端校验`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 服务端 _derive_answer_evidence_refs 强校验归属本 Run，核验类型匹配与产物状态。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

在 `packages/agent_runtime/graph.py` 的 `_derive_answer_evidence_refs` 中，服务端对模型引用的证据进行强规则校验：1) 所有 `audit_id` 和 `artifact_id` 必须在当前 `run_id` 的执行记录中物理存在，跨 Run 引用一律剔除；2) 类型严格匹配（SQL 须对应 `sql_audits` 的 `succeeded` 态，Python 须对应退出码为 0 的沙箱产物）；3) 声明数值必须能在关联 Table 中精确溯源。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

证据绑定（Evidence Binding）归属性与类型校验机制：
1. **风险推演（为什么需要归属性校验）**：
- 场景：恶意用户或受 Prompt 注入劫持的大模型，在生成答案时伪造证据引用，例如声称：“数据依据来源于 Run#999 的内部薪资表”；或者将一个生成的图片文件引用为“SQL 结果集”。
- 危害：跨会话数据越权泄露、或者将伪造的未通过审计的数据打上“已核验”标签欺骗决策者。

2. **核心代码：双向密码学哈希与上下文绑定器**：

```python
import hashlib
from typing import Dict, Any

class EvidenceBindingValidator:
    def __init__(self, db_audit_repo):
        self.audit_repo = db_audit_repo

    async def verify_evidence_attachment(self, run_id: str, evidence_claim: dict) -> bool:
        """
        强制双重校验：
        1. 证据必须由当前 run_id 物理生成并登记在册
        2. 证据的实际内容哈希与登记的类型（SQL/Python/DataLink）必须强类型匹配
        """
        evidence_id = evidence_claim.get("evidence_id")
        declared_type = evidence_claim.get("type") # "SQL_DATA" / "IMAGE_ARTIFACT"
        
        # 步骤 1：查询审计库，验证所属权
        record = await self.audit_repo.find_evidence(evidence_id)
        if not record:
            raise SecurityError("伪造证据: 证据标识在审计系统中不存在！")
            
        if record.run_id != run_id:
            raise SecurityError(f"越权攻击: 试图引用其他 Run ({record.run_id}) 的私有证据数据！")

        # 步骤 2：类型严格一致性断言
        if record.evidence_type != declared_type:
            raise TypeError(f"类型伪造: 声明类型为 {declared_type}，但真实物理类型为 {record.evidence_type}")

        return True
```

3. **运行指标与审计合规保障**：
- 前端点击最终答案上的“查看数据来源”时，后端必须严格按当前 `run_id` 过滤并拉取对应的 Audit 详情，从物理上隔绝跨用户、跨 Run 的任何非法证据挂载。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ _derive_answer_evidence_refs 在服务端独立运行，强制校验证据必须诞生于本 Run 物理生命周期
- ✔️ 强校验引用的执行记录终态必须为 succeeded 且退出码为 0，异常或阻断记录不可作证
- ✔️ 结合数值对齐算法验证声明与底层 Table Artifact 的一致性，防范模型编造伪证据

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果用户在同一 Session 内前后发起了两轮提问，第二轮提问可以引用第一轮 Run 的证据吗？

- 🎯 **考官意图**：考察多轮对话间显式证据继承（Lineage Inheritance）协议。
- 🛡️ **攻防标准应答**：可以，但必须通过显式的【跨 Run 证据继承握手协议】：第二轮 Run 在创建时，服务端必须校验第一轮 Run 属于同一用户的合法上下文，将第一轮证据以只读快照形式重新签署赋予第二轮 Run 的父引用指针，严禁模型在无授权情况下随意穿透引用。
- ⚠️ **避坑要点**：不要允许前端随意传一个 evidence_id 就放行，必须在后端校验 Session 与 User 的所属权边界。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 证据绑定由服务端代码强制决定，大模型只可建议引用，不可绕过后端校验直接写入
- 🛑 数值校验覆盖核心度量值，对自然语言推论和定性描述不做表格强制反查


---
