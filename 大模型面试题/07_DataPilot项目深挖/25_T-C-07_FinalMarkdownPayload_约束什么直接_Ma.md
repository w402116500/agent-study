# T-C-07: `FinalMarkdownPayload` 约束什么？直接 Markdown 探测失败时 `submit_answer` 兜底如何避免接受 SQL、路径或推理字段？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`Agent, 数据契约, 防御性编程`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> FinalMarkdownPayload 仅约束纯 Markdown 正文，兜底方案坚决拒绝接受 SQL 或内部路径字段。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

`FinalMarkdownPayload` 是最终答案的严格 Pydantic 契约，仅包含 `markdown: str`（长度限制在 1~10,000 字符），强行屏蔽一切外部参数。系统优先探测大模型直接输出纯 Markdown 的能力；若模型格式探测失败，触发兜底协议 `submit_answer(markdown=...)`，但该工具在底层严格剔除并丢弃任何夹带的 `sql`、`file_path`、`thought` 等私货字段，防止模型以报告为借口泄露服务器内部路径或注入未审计语句。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

FinalMarkdownPayload 结构约束与 submit_answer 兜底安全防线：
1. **业务场景与防泄露诉求**：
- 场景：在 Final Answer 交付阶段，由于模型非确定性，有时会不慎将执行的内部私有路径（`/tmp/sandbox_1024/raw.csv`）、内部连接串、或者中间思索的 SQL 代码吐到面向普通用户的最终报表中。
- 核心约束：输出必须纯净，只能包含面向用户的最终业务结论与合规 Markdown。

2. **核心代码：FinalMarkdownPayload Pydantic 校验与兜底清洗**：

```python
from pydantic import BaseModel, Field, validator
import re

class FinalMarkdownPayload(BaseModel):
    markdown_content: str = Field(..., description="纯净的业务结论 Markdown 文本")
    key_metrics: Dict[str, Any] = Field(default_factory=dict, description="结构化摘要指标")

    @validator('markdown_content')
    def forbid_internal_leaks(cls, v):
        # 1. 绝对严禁泄露服务器绝对物理路径
        if re.search(r'/(?:var|tmp|home|etc)/[\w\-\./]+', v):
            raise ValueError("禁止在最终答案中泄露服务器内部物理路径")
        # 2. 绝对严禁泄露内部带密度的连接信息
        if "password=" in v or "token=" in v:
            raise ValueError("敏感认证信息泄露拦截")
        return v

def submit_answer_fallback(raw_text: str) -> str:
    """
    当大模型直接生成的 Markdown 触发校验失败时，走清洗兜底机制：
    剥离 SQL 代码块与路径，保留纯文本文字阐述
    """
    # 正则清洗掉 ```sql ... ``` 代码块
    sanitized = re.sub(r'```sql.*?```', '*(相关数据查询已通过安全审计，明细已归档)*', raw_text, flags=re.DOTALL)
    # 正则脱敏本地沙箱路径
    sanitized = re.sub(r'/tmp/sandbox_\w+/', '[安全工作区]/', sanitized)
    return sanitized
```

3. **运行指标与边界防御**：
- 拒绝任何反向参数注入：`submit_answer` 兜底只接收纯文本字符串，绝不接受 `db_path`、`sql_query` 等字段，切断通过 Final Answer 参数反射反向攻击沙箱的一切可能。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ FinalMarkdownPayload 强约束单一 markdown 字段（1~10,000字），杜绝结构冗余
- ✔️ 直接 Markdown 输出为首选，工具调用兜底作为兼容备选
- ✔️ 严格禁止大模型在答案参数中回传物理文件路径或 SQL，证据关系完全由服务端闭环计算

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果用户就是想在报表里看查出来的数据明细，应该如何展示而不是裸露 SQL？

- 🎯 **考官意图**：考察数据消费与底层代码的解耦呈现方式。
- 🛡️ **攻防标准应答**：通过标准 Markdown 表格或数据卡片渲染：系统将 SQL 查询产出的结构化 JSON 数据集转为只读的 Markdown Table 嵌入报表，用户看到的是规整的二维数字报表，而不是底层的 SQL 文本与物理数据库结构。
- ⚠️ **避坑要点**：不要为了省事直接打印 SQL 输出字符串，这破坏了业务抽象与敏感表名保护承诺。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 Markdown 仅作为排版渲染标记，前端渲染组件严格关闭 raw HTML 解析防范 XSS
- 🛑 系统不为大模型提供自定义复杂 JSON 图表配置生成的接口，图表仅以标准图片 Artifact 形式渲染


---
