# R-P3-02: 提到 BGE-M3、Milvus BM25；一次 `hybrid_retrieve` 的输入、两路候选和输出字段分别是什么？

- **归属项目**：`SuperMew` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`RAG, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 输入为原始 Query 与 Embedding；两路各取 Top 30 候选供去重与父子合并；输出包含 chunk_id、parent_id 与归一化分数的统一结构。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

在 SuperMew 的 `hybrid_retrieve` 接口中：输入包括 `query_text`、对应的 1024 维 `query_vector`、`collection_name` 以及租户/版本过滤条件；内部并发发起两路检索：Dense 路查询 `vector` 稠密向量索引取 Top 30，BM25 路基于 Milvus 稀疏倒排索引取 Top 30，两路候选合计最多 60 个；经 RRF 融合与去重后，输出一组包含 `chunk_id`、`parent_chunk_id`、`content`、`rrf_score` 与 `metadata` 的统一候选题元列表，进入后续上卷阶段。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

一次 `hybrid_retrieve` 的输入、两路候选与输出字段契约：
1. **输入契约（Input Contract）**：
- 输入不仅是用户的原始 Query（如“2024Q3资产负债表中流动资产合计是多少”），还包含预生成的 1024 维 BGE-M3 Dense Embedding 向量、可选的元数据过滤条件（如 `doc_id = 'FIN_2024Q3'`），以及请求跟踪 TraceContext。

2. **双路候选与融合处理**：
- **Dense 路**：从 Milvus Dense 集合以 COSINE 度量检索 Top-30 语义相近 Chunk；
- **Sparse 路**：从 Milvus 内置 BM25 全文索引检索 Top-30 关键词匹配 Chunk；
- **输出统一字段**：合并为包含 `chunk_id`, `parent_chunk_id`, `score`, `text`, `metadata` 的标准化结构。

3. **核心代码：双路并行混合检索实现（含逐行注释）**：
```python
import asyncio
from typing import List, Optional
from src.core.types import RetrievalResult, QueryContext

class HybridRetriever:
    """Milvus Dense 与 BM25 双路检索器"""
    def __init__(self, milvus_client, rrf_fusion):
        self.client = milvus_client
        self.fusion = rrf_fusion

    async def hybrid_retrieve(self, ctx: QueryContext, top_k: int = 30) -> List[RetrievalResult]:
        # 1. 启动两路并发异步检索，压低总体 P95 延迟
        dense_task = self._retrieve_dense(ctx.query_vector, top_k=top_k, doc_filter=ctx.doc_filter)
        bm25_task = self._retrieve_bm25(ctx.query_text, top_k=top_k, doc_filter=ctx.doc_filter)
        
        # 使用 asyncio.gather 并行获取候选集
        dense_results, bm25_results = await asyncio.gather(dense_task, bm25_task)

        # 2. 注入链路 Trace 监控指标
        ctx.trace.record("dense_candidates_count", len(dense_results))
        ctx.trace.record("bm25_candidates_count", len(bm25_results))

        # 3. RRF(k=60) 融合排序，输出统一候选
        fused_candidates = self.fusion.fuse([dense_results, bm25_results], top_k=top_k)
        return fused_candidates

    async def _retrieve_dense(self, vector: List[float], top_k: int, doc_filter: Optional[str]) -> List[RetrievalResult]:
        # 调用 Milvus 密集向量检索 API，使用 COSINE 距离
        raw_hits = await self.client.search(
            data=[vector], anns_field="vector", param={"metric_type": "COSINE"},
            limit=top_k, expr=doc_filter, output_fields=["chunk_id", "parent_id", "text"]
        )
        return [RetrievalResult.from_milvus_hit(h) for h in raw_hits[0]]

    async def _retrieve_bm25(self, text: str, top_k: int, doc_filter: Optional[str]) -> List[RetrievalResult]:
        # 调用 Milvus BM25 稀疏全文检索 API
        raw_hits = await self.client.search(
            data=[text], anns_field="sparse_vector", param={"metric_type": "BM25"},
            limit=top_k, expr=doc_filter, output_fields=["chunk_id", "parent_id", "text"]
        )
        return [RetrievalResult.from_milvus_hit(h) for h in raw_hits[0]]
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 输入包含原始文本、1024 维向量与标量租户版本过滤条件
- ✔️ 两路各取 30 个候选（合计最多 60 个）为上卷与去重保留冗余度
- ✔️ 统一输出携带 chunk_id、父子关联键与可观测的名次打分

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果两路召回的候选完全重合（交集为 30），去重逻辑是如何保留得分的？

- 🎯 **考官意图**：考察候选集交集去重、得分融合与文档对象保留机制。
- 🛡️ **攻防标准应答**：如果候选完全重合，RRF 会对每个 chunk_id 累加两路名次倒数得分（如某文档在两路都排第 1，得分即为 1/61 + 1/61 ≈ 0.03278），得分加倍并在排序中牢牢占据前列；文档实体字典保留先进入的实例，避免重复内存分配。
- ⚠️ **避坑要点**：切勿说'按最高分覆盖'，RRF 的核心价值正是通过双路共识累加来顶高两路共同认可的优质候选。

###### 🎯 追问对决：Dense 向量和 BM25 稀疏索引是在 Milvus 的同一个集合里还是不同集合？

- 🎯 **考官意图**：考察 Milvus 2.4+ 多向量与稀疏向量特性（Hybrid Search）的架构理解。
- 🛡️ **攻防标准应答**：在 Milvus 2.4+ 中，它们被保存在同一个 Collection 内部的不同 Field 中（Dense 字段为 FloatVector(1024)，BM25 字段为 SparseFloatVector）。这样可以通过单个 Collection 的 Hybrid Search API 原生并发执行两路检索，避免了维护两个集合带来的元数据不同步与网络往返开销。
- ⚠️ **避坑要点**：不要说'建了两个库各查一次'，现代 Milvus 原生支持多向量与稀疏向量同集合共存。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 `hybrid_retrieve` 仅处理 L3 叶子块的召回与多路打分，尚未执行父块文本拉取
- 🛑 候选数量上限固定受限于内存缓冲区配置，不建议盲目放大超过 100


---
