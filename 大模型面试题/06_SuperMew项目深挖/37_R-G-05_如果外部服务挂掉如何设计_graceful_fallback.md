# R-G-05: 如果外部服务挂掉，如何设计 graceful fallback，同时让报告知道发生过降级？

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`系统设计, RAG, Agent`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 遵循安全降级且状态可观测原则：核心依赖熔断退化走保底通道，并在 Trace 与元数据打上不可磨灭的降级标记。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

设计外部依赖优雅降级（Graceful Degradation）必须坚持两个不可动摇的底线：第一，**宁可降级也不挂起**，比如 Qwen Reranker 精排超时立即退化为 RRF 融合，DataLink 图谱挂掉立即退化为经典只读 Schema，保证业务主链路不中断；第二，**降级必须透明留痕（Never Silent Fallback）**，绝对不能偷偷摸摸降级骗过报告。系统必须在结果元数据、Trace 链路以及最终评测报告中显式注入 `DEGRADATION_TRIGGERED` 标记，让运维和质检人员清晰知晓此次回答是在非完整算力下产出的。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

外部核心依赖（如高精度 Reranker 模型、Docker 沙箱代码引擎）不可用时的安全降级与全链路标记设计：
1. **断路器与降级策略（Circuit Breaker & Fallback Strategy）**：
- 当 Qwen Reranker 服务超时（>800ms）或抛出 503 错误时，断路器立即开启；
- 系统平滑退化为纯 RRF（Reciprocal Rank Fusion）混合检索分数的初筛排序结果输出 Top-8；
- 绝不能因精排不可用直接对用户报错白屏，保证“可用性优先于极致精排”。

2. **核心代码：带熔断与降级元数据标记的检索管道**：

```python
import time
from typing import List, Dict, Any

class RetrievalPipeline:
    def __init__(self, reranker_client):
        self.reranker = reranker_client
        self.failure_count = 0
        self.circuit_open = False

    async def search_with_fallback(self, query: str, candidate_chunks: List[Dict]) -> Dict[str, Any]:
        """带自动熔断降级与不可磨灭 Trace 标记的检索逻辑"""
        degraded = False
        degrade_reason = None
        results = []

        if not self.circuit_open:
            try:
                # 尝试调用高精度 Rerank 模型（超时阈值 800ms）
                results = await self.reranker.rank(query, candidate_chunks, timeout=0.8)
            except Exception as e:
                self.failure_count += 1
                if self.failure_count >= 3:
                    self.circuit_open = True  # 连续 3 次失败开启熔断
                degraded = True
                degrade_reason = f"Reranker unavailable: {str(e)}"
        else:
            degraded = True
            degrade_reason = "Circuit breaker open, bypassed Reranker"

        # 降级路径：直接使用 RRF 初始得分截断
        if degraded:
            results = sorted(candidate_chunks, key=lambda x: x.get("rrf_score", 0), reverse=True)[:8]

        return {
            "chunks": results,
            "metadata": {
                "is_degraded": degraded,
                "degraded_component": "reranker" if degraded else None,
                "reason": degrade_reason,
                "timestamp": time.time()
            }
        }
```

3. **报告层与 Trace 层的不可磨灭感知**：
- **Trace 监控层**：将 metadata.is_degraded = True 写入 Langfuse Trace 的 tags 中，触发告警系统；
- **最终生成报告层**：在生成的输出末尾或元数据角标处注明：*注：本回答基于通用检索生成（精排服务降级），确保调用方知晓答案置信度差异。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 宁可降级也不挂起：Rerank 降级走 RRF，DataLink 降级走原生 Schema
- ✔️ 坚决拒绝静默降级：系统状态机必须在 Trace 与 Payload 中显式标记 is_degraded
- ✔️ 评测报表对降级样本进行独立分流统计，避免偶发网络故障污染算法归因

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：熔断器打开后，什么时候以及如何恢复正常流量（Half-Open 状态）？

- 🎯 **考官意图**：考察分布式弹性设计中经典断路器状态机（Open/Closed/Half-Open）的实现。
- 🛡️ **攻防标准应答**：采用标准三态熔断器：熔断开启（Open）后启动冷却定时器（如 30 秒）。超时后自动进入半开（Half-Open）状态，此时仅允许 10% 的探测流量尝试调用 Reranker。若连续 5 个探测请求成功，则闭合熔断器恢复正常；若再次出现失败，则立即重新熔断并延长冷却时间至 60 秒。
- ⚠️ **避坑要点**：不要说人工手动重启，必须说明自动化半开探测与自愈恢复流程。

###### 🎯 追问对决：如果沙箱代码执行器挂了，有没有降级可能？数据分析 Agent 怎么处理？

- 🎯 **考官意图**：考察对'核心强依赖无法降级时'的业务边界把握。
- 🛡️ **攻防标准应答**：沙箱执行属于强依赖功能（不可降级），若挂掉不能瞎编图表。此时系统必须诚实降级：直接将 SQL 查询返回的结构化表格数据以 Markdown 表格形式呈现给用户，并在界面明确提示'高级图表引擎维护中，已为您展示原始汇总数据'，保证数据真实性第一。
- ⚠️ **避坑要点**：千万不要说让 LLM 脑补绘图，代码执行必须真实，无法执行时退回纯表格展示。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 降级方案针对的是辅助增强模块，若核心基础设施（如主数据库、底层大模型）完全挂掉，系统必须安全终止并报错
- 🛑 降级模式下的打分阈值需适配调整，避免沿用原有的精排阈值导致过滤为空


---
