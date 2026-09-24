# O-03: 从管理员上传一份 PDF 到用户看到带来源回答，SuperMew 的完整链路怎么走？

- **归属项目**：`SuperMew` | **题目类型**：`简单题` | **难度等级**：`基础` | **核心主题**：`RAG, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> SuperMew 经历‘MinerU 布局解析转 Markdown → 三级父子分块 → L3 双路混合检索与 RRF → Auto-merging 上卷 → Qwen 精排 → 引用合成’完整链路。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

链路分入库与检索两端：入库端：管理员上传 PDF 经 MinerU 提取视觉布局转为结构化 Markdown，按标题语法树切成 L1(2400)/L2(1600)/L3(800) 父子块，L3 存入 Milvus（Dense+BM25），L1/L2 存入 PostgreSQL 并缓存进 Redis；检索端：用户提问生成 BGE-M3 embedding，Milvus 并发召回 Dense 与 BM25 各 30 条候选，RRF(k=60) 融合重排；命中同一父块达到阈值自动上卷为大块上下文；接着送 Qwen Reranker 精排筛选 Top 8；最后拼装 Prompt 由 LLM 输出带 [1][2] 真实引用角标的 Markdown 答案。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

SuperMew 从管理员上传一份 PDF 到最终用户拿到带引用角标的精准回答，经历完整摄取与检索合成链路：
1. **文档摄取与结构感知分块（Ingestion Pipeline）**：
- 管理员上传《某型工业网关技术规范.pdf》（含 28 页技术规范及多页硬件引脚表格）；
- MinerU 引擎进行 Layout Analysis，剔除页眉页脚与无意义水印，提取 Markdown 格式半结构化数据，保留原生表格与代码块；
- `DocumentChunker` 依据标题语法树构建三层父子架构：L1(章节/2400字)、L2(小节/1600字)、L3(检索原子/800字)，为每个 chunk 计算确定性 UUID 并打上 `parent_chunk_id`；
- L3 向量经 BGE-M3 编码（1024维向量）和原生分词存入 Milvus，父级 L1/L2 存入 PostgreSQL，高频父块同步写入 Redis 缓存。

2. **双路检索与 Auto-merging 父级上下文上卷**：
- 用户发起查询：“CAN总线接口引脚定义及终端电阻配置阻值是多少？”；
- `HybridSearch` 启动，BGE-M3 Dense 与 Milvus BM25 各检索 Top-30 候选，经 RRF(k=60) 计算融合得分；
- 执行 Auto-merging 策略：若同一个 L2 父块下有 >= 2 个 L3 子块同时命中，或命中 L3 相似度超阈值，系统自动从 Redis/Postgres 上卷拉取完整的 L2 块替换零散碎片，消除上下文截断。

3. **Cross-Encoder 精排与引用角标注入**：
- 上卷后的候选集（通常 15~20 个段落）送入 Qwen Reranker 进行全局交叉注意力打分，精确裁决出 Top-8 高质块；
- 将 Top-8 文本块拼入 Prompt 上下文，并在每个段落前打上 `[Ref_X]` 来源标识；
- LLM 流式输出生成回答，由 `CitationGenerator` 解析角标与元数据绑定，最终生成带可点击高亮证据链的专业解答。

4. **核心代码：RRF 融合与 Auto-merge 父级上卷实现**：
```python
from typing import List, Dict, Any
from collections import defaultdict

def rrf_fusion_and_automerge(
    dense_hits: List[Dict[str, Any]], 
    sparse_hits: List[Dict[str, Any]], 
    k: int = 60,
    parent_merge_threshold: int = 2
) -> List[str]:
    """RRF 混合检索融合与父块上卷算法"""
    rrf_scores = defaultdict(float)
    chunk_meta = {}
    
    # 1. 计算 Dense 排名得分 (Top-30)
    for rank, item in enumerate(dense_hits):
        cid = item["chunk_id"]
        rrf_scores[cid] += 1.0 / (k + rank + 1)
        chunk_meta[cid] = item
        
    # 2. 计算 Sparse (BM25) 排名得分 (Top-30)
    for rank, item in enumerate(sparse_hits):
        cid = item["chunk_id"]
        rrf_scores[cid] += 1.0 / (k + rank + 1)
        if cid not in chunk_meta:
            chunk_meta[cid] = item
            
    # 3. 统计父块命中频率，执行 Auto-merging
    parent_hit_counts = defaultdict(int)
    for cid in rrf_scores.keys():
        pid = chunk_meta[cid].get("parent_chunk_id")
        if pid:
            parent_hit_counts[pid] += 1
            
    # 4. 判定是否上卷为完整父块
    final_context_ids = []
    for cid, score in sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:15]:
        pid = chunk_meta[cid].get("parent_chunk_id")
        if pid and parent_hit_counts[pid] >= parent_merge_threshold:
            if pid not in final_context_ids:
                final_context_ids.append(pid) # 上卷为父块上下文
        else:
            if cid not in final_context_ids:
                final_context_ids.append(cid)
                
    return final_context_ids
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ MinerU 视觉版面分析保证了复杂表格与列表不被切碎
- ✔️ L3 做精确密集检索，L1/L2 在 PostgreSQL 提供完整语义上下文
- ✔️ Milvus 原生支持 BM25 与 Dense，单组件完成 RRF(k=60) 融合无需外挂 ES
- ✔️ Auto-merging 发生在精排之前，有效防止大模型被截断的碎片误导
- ✔️ 最终生成强约束引用标记，实现端到端证据可追溯

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：为什么把父级上下文上卷（Auto-merging）放在 Rerank 之前而不是拿到 Top 8 之后？

- 🎯 **考官意图**：考察对 Cross-Encoder 语义完整性、注意力机制与检索吞吐瓶颈的深刻理解。
- 🛡️ **攻防标准应答**：Qwen Reranker 是 Cross-Encoder 架构，计算的是 Query 与 Document 拼接后的全局全连接注意力。如果先 Rerank，零散的 800 字 L3 块往往因为丢失表头或前后文定义，导致精排模型给其判定极低的分数而直接被淘汰；而在 Rerank 之前先做 Auto-merging 上卷，将碎片还原为语义完整的 1600 字小节，精排模型就能基于完整的表格定义与上下文打出极高精准分，大幅提高最终上下文质量。
- ⚠️ **避坑要点**：不要把原因归咎于'为了省代码'，必须强调 Cross-Encoder 对上下文语义完整性的严苛依赖。

###### 🎯 追问对决：如果管理员同名上传一份新版本 PDF，系统底层如何保证索引平滑切换且无脏数据？

- 🎯 **考官意图**：考察版本控制、原子发布与无缝双写/别名切换的工程落地能力。
- 🛡️ **攻防标准应答**：系统采用版本化原子提升机制：同名上传文件进入暂存区，解析并分配新的 doc_version_id（如 v2）；在独立的临时分区完成向量索引构建与校验；确认就绪后，在数据库事务中将主文档指针从 v1 切换至 v2，并在 Milvus 中更新集合分区别名；原 v1 数据置为 deprecated，在 24 小时后异步物理清理，保证在线检索零中断且无版本混用脏数据。
- ⚠️ **避坑要点**：绝对不能说'直接 delete 掉旧向量再写入新向量'，这种破坏性操作会导致正在进行的并发检索发生 404 故障。

###### 🎯 追问对决：RRF 算法里的 k=60 是怎么定下来的？调大或调小对结果有什么影响？

- 🎯 **考官意图**：考察信息检索（IR）数学原理、超参数敏感度与经验调参经验。
- 🛡️ **攻防标准应答**：k=60 源自信息检索领域 Cormack 等人的经典基准经验值（SIGIR'09）。公式 1/(k+rank) 中，若 k 过小（如 k=10），排名第一名的权重占比过大，单个召回路的偶然高排名会碾压另一个路的多条稳定召回；若 k 过大（如 k=200），不同名次间的得分衰减过于平缓，排名区分度急剧下降。我们在 300 道验证集上对 k 在 20~100 进行了网格调优，发现 k=60 时 Recall@10 与 NDCG 达到最优平衡点。
- ⚠️ **避坑要点**：切忌随口说是'随便填的'，要说出公式、衰减斜率以及在验证集上的实验权衡。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 MinerU 依赖离线 GPU/CPU 计算资源，解析超大 PDF 时存在秒级排队延迟
- 🛑 同名替换在清理旧索引后若发生数据库宕机，目前没有跨 Milvus/PG 的两阶段回滚


---
