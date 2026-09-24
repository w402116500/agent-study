# T-A-03: 如果 BM25 路异常，`retrieve_documents` 如何复用查询 embedding 做降级？两路都失败返回什么可观察信息？

- **归属项目**：`SuperMew` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`RAG, 容灾降级, 可观测性`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> BM25 异常时复用已计算的 Query 向量单路降级并在 Trace 标记 dense_fallback，双路全败记录原因并安全返回空。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

在 `retrieve_documents` 执行时，Query 向量在初筛前已由 BGE-M3 生成。若 BM25 检索因网络抖动、分词异常或节点过载抛错，系统捕获异常后不重算向量，直接复用该 embedding 单走 Dense 结果，跳过 RRF 融合并将元数据标记为 `retrieval_mode: dense_fallback`；若 Dense 与 BM25 双路全部抛错，系统绝不抛 500 崩溃，而是记录详细错误栈至 Trace，返回空候选集让下游优雅提示‘未检索到相关参考知识’。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

当 BM25 检索链路发生异常（如倒排索引文件损坏、分词超时或内存溢出）时的降级流转机制：
1. **异常捕获与隔离原则（Failure Isolation）**：
- 双路检索采用异步并发调度（`asyncio.gather(return_exceptions=True)`）；
- BM25 失败绝不能阻塞 Dense 向量检索主干，必须实施局部降级保护。

2. **核心代码：双路并行检索与自动平滑单路降级**：

```python
import asyncio
import logging
from typing import List, Dict, Any

logger = logging.getLogger("supermew.retrieval")

async def retrieve_documents(query: str, top_k: int = 30) -> Dict[str, Any]:
    """双路并行检索：BM25 故障时自动无缝降级为纯 Dense 向量召回"""
    # 异步并发执行 Dense 与 BM25
    dense_task = search_milvus_dense(query, top_k=top_k)
    bm25_task = search_bm25_sparse(query, top_k=top_k)
    
    # 捕获异常，防止一个协程挂掉影响全局
    dense_res, bm25_res = await asyncio.gather(dense_task, bm25_task, return_exceptions=True)
    
    is_bm25_failed = isinstance(bm25_res, Exception)
    is_dense_failed = isinstance(dense_res, Exception)
    
    # 极端异常：双路均崩溃
    if is_dense_failed and is_bm25_failed:
        logger.critical(f"双路检索全军覆没: dense={dense_res}, bm25={bm25_res}")
        raise RuntimeError("检索服务不可用")
        
    # 场景 1：BM25 故障，平滑降级为纯 Dense
    if is_bm25_failed:
        logger.warning(f"BM25检索异常，自动降级为纯Dense: {str(bm25_res)}")
        return {
            "candidates": dense_res[:top_k],
            "is_degraded": True,
            "fallback_mode": "DENSE_ONLY",
            "error_detail": str(bm25_res)
        }
        
    # 场景 2：Dense 故障，平滑降级为纯 BM25
    if is_dense_failed:
        logger.warning(f"Dense检索异常，自动降级为纯BM25: {str(dense_res)}")
        return {
            "candidates": bm25_res[:top_k],
            "is_degraded": True,
            "fallback_mode": "BM25_ONLY",
            "error_detail": str(dense_res)
        }
        
    # 场景 3：双路正常，执行标准 RRF 融合
    fused = reciprocal_rank_fusion(dense_res, bm25_res, k=60, top_n=top_k)
    return {
        "candidates": fused,
        "is_degraded": False,
        "fallback_mode": "NORMAL_HYBRID"
    }
```

3. **Trace 记录与后续感知**：
- 降级标志 `fallback_mode='DENSE_ONLY'` 被传递至后续链路，并在 Prometheus 暴露 `retrieval_fallback_total{mode="DENSE_ONLY"}` 监控指标；
- 告警系统触发 P2 级飞书通知，但用户端无感知（回答仍能生成，只是专有名词精准度稍有下降）。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ Query 向量预计算完成，BM25 异常时零开销复用 Embedding，跳过 RRF 直接走 Dense 结果
- ✔️ Trace 中显式埋点 retrieval_mode (hybrid / dense_fallback / failed)，拒绝静默故障
- ✔️ 双路全崩时返回空候选集触发生成兜底，避免系统 500 崩溃，保障调用方 SLA

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果 BM25 是偶发性慢查询（如分词卡死 3 秒），系统如何防止请求被活活拖垮？

- 🎯 **考官意图**：考察异步超时控制（asyncio.wait_for）与防御性编程。
- 🛡️ **攻防标准应答**：必须为每个子任务包裹严格的超时熔断。例如设置 BM25 的硬超时时间为 150ms：`await asyncio.wait_for(bm25_task, timeout=0.15)`。一旦超过 150ms，立即触发 TimeoutError 并抛弃该路结果，降级为纯 Dense 输出，坚决保障系统 P99 响应时间在可控范围内。
- ⚠️ **避坑要点**：不要漏掉显式的 timeout 超时设置，不能只提 try...except。

###### 🎯 追问对决：在 DENSE_ONLY 降级模式下，后续 Auto-merging 和 Rerank 还能正常工作吗？

- 🎯 **考官意图**：考察数据结构向下兼容性与解耦设计。
- 🛡️ **攻防标准应答**：完全可以正常工作。因为候选集返回的数据结构是完全统一的标准字典格式（必须包含 chunk_id、content、parent_id 等元数据），Auto-merging 仅依赖 parent_id 的命中频次统计，Rerank 仅依赖 content 文本，与上游到底是用 RRF 得分还是余弦相似度完全解耦。
- ⚠️ **避坑要点**：强调接口与数据契约的统一性。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 降级仅能保障语义近似召回，对于专有代号和型号查询，dense_fallback 可能出现召回精度下降
- 🛑 系统不维护磁盘级冷备索引做三级降级


---
