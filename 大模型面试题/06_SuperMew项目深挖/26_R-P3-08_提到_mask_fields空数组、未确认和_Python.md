# R-P3-08: 提到 `mask_fields`；空数组、未确认和 Python 输出的语义分别是什么？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`SQL, Sandbox, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> mask_fields 为空数组代表全脱敏，未确认代表不放行，明确字段列表执行精准哈希掩码；Python 不自动脱敏需通过网关快照可信注入。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

`mask_fields` 语义必须极其严谨：如果配置为明确的列表 `['phone', 'id_card']`，数据网关只针对这几个列进行精准掩码；如果配置为 `[]`（空列表），语义是‘全量敏感字段严格全脱敏’；如果处于未确认状态，系统视作最高安全级别阻断放行。至关重要的一点是：Python 沙箱的 stdout 与 Artifact **没有也不应该自动套用脱敏规则**，因为沙箱与外网物理隔离，它处理的数据来自数据网关已经脱敏好的输入快照，这种分层设计避免了在 Python 输出端盲目用正则表达式搞坏图表数据。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

`mask_fields` 的全脱敏、未确认与精确掩码三种语义处理：
1. **三种语义的严格契约**：
- `mask_fields = []`（空数组）：**全量脱敏**，对该数据源内所有可能涉及隐私的字段（姓名、手机号、卡号、金额）全部打码；
- `mask_fields = None`（未确认）：**拒绝放行**，必须等待管理员或用户确认脱敏策略后才能提取数据；
- `mask_fields = ['phone', 'id_card']`：**精准掩码**，对指定字段执行哈希或部分星号打码。

2. **核心代码：字段脱敏策略执行器（含逐行注释）**：
```python
import hashlib
from typing import List, Dict, Any, Optional

class DataMasker:
    """可信数据脱敏处理器"""
    @staticmethod
    def apply_masking(records: List[Dict[str, Any]], mask_fields: Optional[List[str]]) -> List[Dict[str, Any]]:
        # 语义 1：未确认时拒绝放行，抛出安全异常
        if mask_fields is None:
            raise PermissionError("Security: mask_fields is unconfirmed, data export blocked")

        masked_data = []
        is_mask_all = len(mask_fields) == 0  # 语义 2：空数组表示全量脱敏

        for row in records:
            new_row = {}
            for k, v in row.items():
                if v is None:
                    new_row[k] = None
                    continue
                # 判断字段是否需要脱敏
                if is_mask_all or k in mask_fields:
                    val_str = str(v)
                    # 规则：手机号保留前 3 后 4，其余打星号；其余字段做加盐 SHA256 哈希前 8 位
                    if "phone" in k.lower() and len(val_str) == 11:
                        new_row[k] = val_str[:3] + "****" + val_str[7:]
                    else:
                        new_row[k] = "MASK_" + hashlib.sha256(val_str.encode()).hexdigest()[:8]
                else:
                    new_row[k] = v
            masked_data.append(new_row)
        return masked_data
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ mask_fields 包含明确列表、全量严格掩码与未决阻断三态严谨语义
- ✔️ 坚决否决正则模糊猜测，严格依赖数据字典静态元数据声明
- ✔️ Python 容器依赖源头脱敏快照注入，输出端不设正则以防破坏业务报表

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果业务要求 Python 脚本必须在图表标题上打印脱敏后的客户名字，如何保证合规？

- 🎯 **考官意图**：考察脱敏数据与业务呈现的结合处理。
- 🛡️ **攻防标准应答**：网关在数据快照阶段已将真实客户名字替换为统一脱敏标识（如 '张*丰' 或 'HASH_8F2A'），Python 脚本在沙箱中仅能接触到脱敏后的字符串，因此即使绘制在图表标题或坐标轴上，也绝对不会泄露任何原始敏感真实身份。
- ⚠️ **避坑要点**：切忌说'让大模型在画图时自己打码'，合规性不能寄托于大模型的自觉，必须在数据入口物理脱敏。

###### 🎯 追问对决：对于数字型数据（如银行卡存款余额），脱敏算法通常如何做泛化或扰动？

- 🎯 **考官意图**：考察数据差分隐私与数值泛化工程实践。
- 🛡️ **攻防标准应答**：采用区间分箱泛化（Bucketization，如将 128,450 元映射为 '[10万-20万]'）或拉普拉斯差分隐私扰动（Laplace Noise），在保持宏观统计分布特征的同时消除对单个具体账户的精准指纹识别。
- ⚠️ **避坑要点**：不要把所有数字都粗暴打星号成 '***'，否则下游 Python 脚本将无法进行求和与均值等数学计算。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 脱敏算法在数据网关层同步执行，若返回行数巨大需注意序列化 CPU 性能开销
- 🛑 Python 脚本内部可对已脱敏数据做二次聚合，但无法逆向推导出原始真实 PII


---
