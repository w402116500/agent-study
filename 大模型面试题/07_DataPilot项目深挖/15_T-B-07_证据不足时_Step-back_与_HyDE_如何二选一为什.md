# T-B-07: 证据不足时 Step-back 与 HyDE 如何二选一？为什么不让每个子问题都再次改写？

- **归属项目**：`SuperMew` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`RAG, 查询改写, 策略选型`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 具体长尾/缺前提选 Step-back 提炼上位概念；抽象口语选 HyDE 补齐词汇；子问题严禁二次改写防雪崩。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

当初始检索证据不足时，系统依据意图类型精准路由：若问题过于细碎或深陷末节（如询问冷门配置参数），走 Step-back（后退一步）提取高层概念或原理规则；若问题极度抽象或偏口语化，走 HyDE 生成伪文档假说以扩充领域术语。但无论哪种，改写预算硬卡为 1 次，严禁对已拆解出的子问题再做二次改写，防止请求发散与延迟雪崩。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

证据不足时 Step-back 与 HyDE 的二选一决策树：
1. **决策树准则（何时用哪个）**：
- **场景 A：选 Step-back（回退抽象）**：
  - 特征：问题极其狭窄、充满生僻专有名词或条件苛刻，导致初次检索返回为空或得分极低（如“在 SuperMew 的 AST 嵌套切分中，遇到 LaTeX 公式与矩阵时如何不截断符号？”）。
  - 动作：回退一步提炼高维原理：“Markdown 解析器如何处理嵌套数学公式的完整性”。
- **场景 B：选 HyDE（假设文档生成）**：
  - 特征：用户提问极短、偏向口语化但意图明确，知识库内无直接同义词（如“系统挂了怎么赔钱？”）。
  - 动作：让 LLM 先写一段虚拟的标准应答应答：“根据 SLA 协议第 4 条，系统不可用达 99.9% 以下按季度服务费的 10% 进行代金券补偿...”，以该虚拟文档去检索真实的《客户服务SLA补偿规范.pdf》。

2. **核心代码：动态改写路由与证据不足熔断器**：

```python
from typing import Optional

class QueryExpansionRouter:
    def __init__(self, llm_client, retriever):
        self.llm = llm_client
        self.retriever = retriever

    async def retrieve_with_fallback(self, query: str, initial_docs: list) -> list:
        # 1. 评估初次检索的置信度（最高分阈值检查）
        max_score = max([d.get("score", 0.0) for d in initial_docs]) if initial_docs else 0.0
        
        # 若初筛分数合格（>0.72），坚决不进行任何二次改写，保护延迟与成本！
        if max_score >= 0.72:
            return initial_docs

        # 2. 证据不足触发自适应路由选择
        strategy = self._classify_query_strategy(query)
        
        if strategy == "STEP_BACK":
            # 提炼更高维度的宏观概念
            rewritten_q = await self.llm.generate(f"请提炼出以下具体问题的通用原理与宏观背景问题: {query}")
            return await self.retriever.search(rewritten_q)
        elif strategy == "HYDE":
            # 构造虚拟假设文档做语义对齐
            hypothetical_doc = await self.llm.generate(f"请根据企业规范假设一段回答该问题的标准文档段落: {query}")
            return await self.retriever.search(hypothetical_doc)
        
        return initial_docs

    def _classify_query_strategy(self, query: str) -> str:
        # 短文本口语倾向 HyDE，复杂多条件特定术语倾向 STEP_BACK
        if len(query) < 15 and ("怎么" in query or "如何" in query):
            return "HYDE"
        return "STEP_BACK"
```

3. **为什么严禁让每个子问题都再次改写**：
- 延迟与爆炸风险：若 4 个子问题每个都串联 HyDE/Step-back，将产生 4 次额外 LLM 推理与 4 次向量检索，P99 延迟直接从 600ms 恶化至 4s 以上，且引入“假设文档本身的幻觉带偏检索”的严重次生灾害。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 细碎末节问题用 Step-back 提炼上位概念，简短口语问题用 HyDE 伪造假说丰富术语
- ✔️ 两类改写相互排斥，根据分类器一选一执行，不串联调用
- ✔️ 严禁子问题嵌套二次改写，单请求硬锁 1 次改写预算，根绝延迟与费用雪崩

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：HyDE 假设出来的段落若本身包含虚假数字，为什么还能检索出真实文档？

- 🎯 **考官意图**：考察向量检索中的语义空间捕获与精确事实匹配的本质区别。
- 🛡️ **攻防标准应答**：因为向量模型（Dense Embedding）在潜在空间中对齐的是语体结构、上下文语法和领域词汇分布（例如 SLA、补偿比例、不可用时长等专业语境），而非校验单个数字真伪。假设文档的作用是充当语义锚点，吸引具有相似词频和句式的正例文档被检索出来。
- ⚠️ **避坑要点**：不要把 HyDE 生成的文本直接拼进 Prompt 喂给最终模型，它只能作为检索向量探针，用完即弃。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 改写属于初次检索置信度不足（Rerank 最高分 < 0.35）时的二次尝试机制，初筛高分时不触发
- 🛑 HyDE 采用最小参数规模模型生成（如 Qwen-1.5B/7B），避免大模型延迟过重


---
