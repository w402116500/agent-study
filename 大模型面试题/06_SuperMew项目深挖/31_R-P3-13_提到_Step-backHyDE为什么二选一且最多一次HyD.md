# R-P3-13: 提到 Step-back/HyDE；为什么二选一且最多一次，HyDE 文本如何防止被当成真实证据？

- **归属项目**：`SuperMew` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`RAG, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 二选一且最多一次避免错误放大与延迟膨胀；HyDE 伪文档仅充当瞬时查询向量探针，绝不进入最终上下文。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

在 SuperMew 中，改写预算被硬性死卡为 `Rewrite Budget = 1`，且 Step-back（后退提问）与 HyDE（假设性文档嵌入）绝不同时触发！因为改写会使大模型调用次数翻倍，多轮改写极易偏离原始意图并放大幻觉。我们根据初次检索得分动态路由：若 Query 极其抽象概念化，触发 Step-back 获取高层背景；若 Query 缺失上下文，触发 HyDE 生成一段假设性回答。关键是：**HyDE 生成的假内容仅在内存中编码为向量后立即丢弃**，绝不允许作为真实证据送入大模型，从物理上杜绝假证据污染！

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

Step-back 与 HyDE 二选一路由机制与防偏航控制：
1. **二选一与防偏航设计原则**：
- **二选一硬约束**：每个查询扩展分支只允许选用 Step-back 或 HyDE 之一，绝不允许连续叠加改写导致问题严重走样；
- **HyDE 假想文本防污染**：HyDE 生成的假想答案仅用来提取向量特征，严禁把假想文本直接注入大模型的上下文作为事实依据！

2. **核心代码：查询扩展路由器实现（含逐行注释）**：
```python
from typing import Optional, Tuple
from src.core.types import QueryContext

class QueryExpansionRouter:
    """Step-back 与 HyDE 二选一查询扩展路由器"""
    def __init__(self, llm_client):
        self.llm = llm_client

    async def route_and_expand(self, ctx: QueryContext) -> Tuple[str, str]:
        # 1. 判断是否需要查询扩展（长尾专有名词或条件过多走 step-back，过于简短口语走 hyde）
        if len(ctx.query_text) < 15:
            # 场景 A：短文本走 HyDE 假设性文档嵌入
            hypothetical_doc = await self._generate_hyde(ctx.query_text)
            # 记录 Trace 标记，仅用作检索向量提取
            ctx.trace.record("expansion_strategy", "HYDE")
            return hypothetical_doc, "HYDE"
        elif any(term in ctx.query_text for term in ["错误码", "版本号", "未找到", "失败"]):
            # 场景 B：针对具体故障条件走 Step-back 提炼高层原理
            step_back_query = await self._generate_step_back(ctx.query_text)
            ctx.trace.record("expansion_strategy", "STEP_BACK")
            return step_back_query, "STEP_BACK"
        
        # 默认直接检索，不改写
        return ctx.query_text, "DIRECT"
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 死卡 Rewrite Budget = 1，防止时延膨胀与语义漂移引起的错误无限放大
- ✔️ Step-back 针对具体参数提问拉取宏观背景，HyDE 针对极短口语化提问补全特征
- ✔️ HyDE 假想文本编码后物理销毁，仅作为检索探针，绝不进入最终大模型上下文

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果 Step-back 改写出的高层问题检索到的内容太多太宽泛，如何避免冲淡原问题的精确回答？

- 🎯 **考官意图**：考察上位概念检索结果与原始精细检索结果的上下文权重分配。
- 🛡️ **攻防标准应答**：在上下文装配阶段实施非对称配额控制：原始问题检索结果分配 70% 的上下文预算，Step-back 上位原则仅分配 30% 预算作为补充背景；同时 Cross-Encoder 精排时仍以原始 Query 为对比基准，有效过滤宽泛无用噪音。
- ⚠️ **避坑要点**：不要把 Step-back 的结果和原始结果完全同等对待，上位知识只能作背景参考。

###### 🎯 追问对决：HyDE 在面对知识库中从未见过的专有名词时，会不会生成完全相反的假想文本导致检索偏航？

- 🎯 **考官意图**：考察对 HyDE 幻觉漂移缺陷的深刻理解与工程补救措施。
- 🛡️ **攻防标准应答**：确实存在此风险。因此系统在短文本路由前设计了'专有名词快筛'：若 Query 中命中未收录在词典中的生僻代号，严禁触发 HyDE，强制退化为 BM25 稀疏检索；即使触发 HyDE，也保留 50% 原始查询词做混合向量融合，防止完全偏航。
- ⚠️ **避坑要点**：不能迷信 HyDE 万能，必须指出其在未知专有名词下的幻觉放大风险并给出词典阻断措施。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 改写仅作为初次检索失败后的兜底手段，85% 的常规事实查询直接走单次混合检索
- 🛑 若知识库语料极度专业且生僻，HyDE 效果会显著下降，此时优先倾向 Step-back 或澄清


---
