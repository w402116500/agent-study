# T-D-04: `mask_fields=null`、`mask_fields=[]` 和非空字段列表分别表示什么？为什么不按列名或样例自动猜敏感字段？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`Agent, 数据脱敏, 隐私合规`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> null 表示不脱敏，[] 表示全列脱敏，列表表示显式指定列；猜测列名必然漏判误判破坏系统稳定性。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

`mask_fields` 遵循确定性语义：`null` 表示未启用列遮蔽（原样透出）；`[]`（空列表）表示进入绝对隐私隔离模式（所有列全部整格替换为 `[MASKED]`）；指定非空字符串列表（如 `['phone', 'id_card']`）表示仅精准遮蔽这些列。坚决不能根据列名猜测敏感字段，因为企业列名经常使用非标拼音、简称（如 `sjhm`、`c1`）或业务代码，自动猜测必然导致漏判造成数据泄露，或误杀核心分析指标。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

mask_fields 三种取值的严格语义与拒绝自动猜测原则：
1. **三种取值的严谨语义规范**：
- `mask_fields = null`（默认继承策略）：严格继承数据源在元数据管理后台预设的全局敏感字段规则（如预设的 `phone`, `id_card`, `bank_account` 进行 SHA256/掩码脱敏）。
- `mask_fields = []`（明确豁免脱敏）：显式声明本次查询不需要任何脱敏（通常用于内部无敏维表查询，或系统级后台聚合任务）。必须有严格的调用者高权限鉴权校验。
- `mask_fields = ["user_name", "email"]`（显式指定脱敏）：精准覆盖并追加脱敏列，除全局规则外，强制对列表中声明的具体列进行脱敏（显示为 `张**` 或 `a***@corp.com`）。

2. **为什么系统坚决不按列名或采样数据“自动猜测敏感字段”**：
- **灾难性误杀与假阳性（False Positive）**：若按名称猜测，`amount`（金额）或 `order_status` 可能因为偶然包含数字被正则误判为手机号，导致业务计算直接把真实金额脱敏为 `***`，彻底破坏下游聚合计算。
- **致命漏判与假阴性（False Negative）**：许多敏感数据存放在非标准列名中（如 `ext_info_json`, `remark_1`），自动猜测一旦失效导致明文直接暴露给大模型，造成严重的数据合规责任事故。

3. **核心代码：显式可预期的数据脱敏引擎**：

```python
from typing import List, Dict, Any, Optional

class DataMaskingEngine:
    def __init__(self, global_datasource_rules: Dict[str, str]):
        self.global_rules = global_datasource_rules  # 比如 {"phone": "MASK_PHONE", "ssn": "MASK_ALL"}

    def apply_masking(self, records: List[Dict[str, Any]], mask_fields: Optional[List[str]]) -> List[Dict[str, Any]]:
        # 1. 确定最终需要脱敏的目标列名集合
        if mask_fields is None:
            target_cols = set(self.global_rules.keys())
        else:
            target_cols = set(mask_fields)

        if not target_cols:
            return records

        masked_output = []
        for row in records:
            new_row = {}
            for k, v in row.items():
                if k in target_cols:
                    new_row[k] = self._mask_value(str(v))
                else:
                    new_row[k] = v
            masked_output.append(new_row)
        return masked_output

    def _mask_value(self, val: str) -> str:
        if len(val) <= 4:
            return "***"
        return val[:2] + "****" + val[-2:]
```

4. **安全底线**：安全边界必须建立在**确定性元数据规则（Deterministic Policy）**之上，严禁将数据合规押注在概率性的启发式正则或猜测模型上。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ mask_fields 清晰定义 null（不遮蔽）、[]（全部遮蔽）与非空列表（精准遮蔽）三态语义
- ✔️ 拒绝通过正则或关键字盲目猜测列名，杜绝非标命名导致的敏感信息漏判
- ✔️ 拒绝通过正则扫描样例数值，防止将产品型号与流水号误判遮蔽导致业务瘫痪

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果用户在 SQL 中通过 SELECT user_name AS u FROM users 给列起别名，脱敏规则如何防穿透？

- 🎯 **考官意图**：考察 AST 别名回溯追踪（Alias Lineage Tracing）机制。
- 🛡️ **攻防标准应答**：通过 sqlglot AST 建立血缘映射（Lineage Tracking）：解析 SELECT 表达式时，追踪每个投影项底层真实的物理列名（Origin Column）。哪怕模型起了别名 `AS u`，系统识别出其源于敏感列 `user_name`，仍然无条件对输出的 `u` 列执行脱敏处理。
- ⚠️ **避坑要点**：不要只按输出结果集的 key 来匹配脱敏规则，必须在 AST 层面对齐底层真实物理字段。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 mask_fields 遮蔽当前采用整格替换为 '[MASKED]' 的安全策略，不提供易受反推的部分打码
- 🛑 脱敏承诺仅覆盖 SQL 结构化输出与前端预览 Artifact，不自动穿透至外部不可控系统


---
