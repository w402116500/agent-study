# O-06: 如果一个外部模型、Rerank 服务或 DataLink 服务不可用，系统怎样降级，用户能看到什么？

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`系统设计, RAG, Agent, MCP`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 系统按‘关键链路优先保障、非关键链路平滑降级、不可用明确提示’分层降级，确保无静默吞错和死锁挂起。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

当外部依赖挂掉时：1. SuperMew 中：若 Milvus BM25 挂掉，自动退化为纯 Dense 向量召回；若 Qwen Reranker 精排超时（超 2s）或报错，系统直接保留上卷后的 RRF 原始排序，并在 Trace 标记 `rerank_fallback=true`；若重写模型挂掉直接跳过改写；2. DataPilot 中：若 FastMCP DataLink 服务不可用，系统优雅降级为‘纯 DDL Schema-only’模式，继续支持标准分析；若模型或核心 Gateway 宕机，通过全局单调 seq 写入失败事件终止 Run，并在前端明确告知用户故障原因，决不返回伪造数据或无端挂起。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

系统针对各类外部脆弱依赖设计了完善的'熔断降级 + 透明外显'机制，确保任何单点故障均不导致雪崩：
1. **外部大模型 LLM API 故障/限流（HTTP 429/500/超时）**：
- **降级行为**：三次指数退避重试（1s、2s、4s）；若仍失败，熔断器打开，DataPilot 立即将已成功执行的 SQL/沙箱中间结果固化为 Partial 状态，终止工具循环；
- **用户外显**：前端提示“上游推理服务繁忙，已为您保留当前已查询到的 3 项事实数据”，展示稳定错误码 `LLM_PROVIDER_UNAVAILABLE`，提供“重试当前步骤”按钮。

2. **Qwen Reranker 精排服务超时或不可用**：
- **降级行为**：SuperMew 设置严格的 5 秒硬超时；一旦精排服务超时或返回 500，系统静默降级，跳过 Reranker，直接按照前置 RRF 融合分数截取 Top-8；
- **用户外显**：回答正常生成，但在来源引用卡片上打上黄色角标标签：`[精排降级-采用初筛排序]`，并在 Trace 元数据中显式记录 `rerank_applied=False` 供监控告警。

3. **DataLink 图谱服务离线**：
- **降级行为**：DataPilot 的 FastMCP Client 探测超时（2s）后，自动退化为只读从库的 `Schema-only` 原生发现模式；
- **用户外显**：Agent 仍然能够根据标准表结构生成 SQL，仅在调试面板标记“语义拓扑图谱离线，部分复杂表间关系将依据外键定义进行推导”。

4. **核心代码：Rerank 硬超时与熔断降级装饰器**：
```python
import asyncio
import logging
from typing import List, Dict, Any

logger = logging.getLogger("FallbackHandler")

async def rerank_with_graceful_fallback(
    query: str, 
    candidates: List[Dict[str, Any]], 
    rerank_client,
    timeout_sec: float = 5.0
) -> List[Dict[str, Any]]:
    """带 5s 熔断降级的精排调用封装"""
    try:
        # 强制增加硬超时保护，绝不阻塞用户主线程
        ranked_results = await asyncio.wait_for(
            rerank_client.rank(query=query, documents=candidates),
            timeout=timeout_sec
        )
        for doc in ranked_results:
            doc["rerank_applied"] = True
        return ranked_results
    except (asyncio.TimeoutError, Exception) as err:
        # 捕获超时或网络 500 异常，实施原地降级
        logger.warning(f"Reranker 服务异常 ({type(err).__name__})，触发原地降级为 RRF 排序")
        # 直接按前序 RRF 分数排序并截取 Top-8
        fallback_results = sorted(candidates, key=lambda x: x.get("rrf_score", 0), reverse=True)[:8]
        for doc in fallback_results:
            doc["rerank_applied"] = False
            doc["fallback_reason"] = "RERANKER_TIMEOUT_FALLBACK"
        return fallback_results
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ Reranker 故障降级保留 RRF 原始排序，零额外 Embedding 成本
- ✔️ DataLink 故障降级至原生 DDL Schema 模式，业务链路不中断
- ✔️ 混合检索单路异常支持单 Dense 容灾
- ✔️ 不可恢复故障必须通过单调 seq 事件落库并推至前端，给出清晰错误码

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如何防止降级后的回答给用户造成‘回答正常但其实不准’的错觉？

- 🎯 **考官意图**：考察用户信任度建设、可解释性与前端反馈闭环设计。
- 🛡️ **攻防标准应答**：系统杜绝'静默假成功'。在底层降级时，Trace 上下文会生成带有降级标志的元数据，前端回答卡片不仅会在顶部打出黄色提示条'精排服务抖动，答案召回可能不全'，还在具体的引用来源中明确标注匹配度来源为初筛分数，同时在日志中打上标签，提醒用户对该条结论进行复核。
- ⚠️ **避坑要点**：千万不能说'降级了就悄悄用初筛结果，用户看不出来的'，企业级场景对准确性要求极高，欺瞒用户是严重事故。

###### 🎯 追问对决：在 trace 监控后台如何统计降级率？有哪些核心告警指标？

- 🎯 **考官意图**：考察生产级可观测性、SLA 指标定义与 Prometheus 告警规则设计。
- 🛡️ **攻防标准应答**：在每次查询的 Trace 结构体中埋入 `retrieval_mode`(hybrid/dense_only) 与 `rerank_applied`(bool)。Prometheus 采集并统计核心指标：1) Rerank 降级率：`rate(rerank_fallback_total[5m]) / rate(query_total[5m])`，阈值超 5% 触发 P2 告警；2) 精排 P99 延迟；3) 外部模型 429 限流错误率。告警直接推送企微/钉钉群。
- ⚠️ **避坑要点**：不要说'看日志文件'，必须给出具体的指标算子、监控系统（Prometheus）与告警阈值。

###### 🎯 追问对决：如果 Qwen Reranker 只是偶尔抖动，熔断器应该采用什么策略防止频繁震荡？

- 🎯 **考官意图**：考察微服务断路器（Circuit Breaker）原理与状态迁移实现。
- 🛡️ **攻防标准应答**：采用标准的三态熔断器模型（Closed、Open、Half-Open）：在 10 秒滑动窗口内若失败率超过 30%，熔断器从 Closed 跃迁为 Open，阻断所有请求直接走降级逻辑；保持 Open 状态 30 秒后进入 Half-Open 状态，仅放行 5% 的试探流量给 Reranker，若连续 10 个请求成功则完全恢复 Closed，否则重新打开，有效消除服务震荡。
- ⚠️ **避坑要点**：不能只说'加个重试'，频繁重试在服务抖动时只会瞬间打垮濒临崩溃的微服务。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 降级只保证系统不崩溃且能给出基于现有证据的回复，不承诺降级后的准确率与全功能一致
- 🛑 核心数据库 PG 宕机属于致命单点故障，系统无法降级，直接拒绝接入


---
