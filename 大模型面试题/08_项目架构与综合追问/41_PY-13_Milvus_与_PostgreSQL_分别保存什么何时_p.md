# PY-13: Milvus 与 PostgreSQL 分别保存什么？何时 pgvector 足够，何时需要独立向量库？

- **归属项目**：`SuperMew` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`数据库选型, Milvus, PostgreSQL, pgvector`
- **可信级别**：项目事实 / 深度选型

> 💡 **一句话速记结论**：
> PG 存业务关系实体与切块元数据；百万级内 pgvector 足够，千万级高吞吐与专用混合检索首选 Milvus。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

两者的分工非常清晰：PostgreSQL 负责结构化业务数据、租户权限 ACL、用户会话历史与切块原始文本的强一致存储；Milvus 专用于高维向量索引（Dense Vector）与倒排稀疏索引（Sparse BM25）的高速相似度检索。什么时候 pgvector 就够了？数据量在 10 万到 100 万以内、且需要频繁在同一个 SQL 事务中把向量检索与复杂的业务表权限做 `JOIN` 关联时，单体 PostgreSQL + pgvector 最合适，架构极简；当数据量突破千万级、追求极致 QPS 吞吐、或者需要成熟的向量分片集群与原生混合多路检索时，必须选用独立向量数据库 Milvus。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

Milvus 与 PostgreSQL 在企业级 RAG 中的职责划分及选型决策标准：
1. **两者的核心职责与存储物理边界**：
- **PostgreSQL（结构化关系数据与事实基石）**：
  - 存储对象：用户租户元数据、文档切块层级树（Parent-Child 关系）、操作审计日志、会话上下文以及具备 ACID 事务要求的数据。
  - 强项：复杂多表关联（JOIN）、强行级行权限（RLS）、JSONB 半结构化灵活查询、金融级一致性。
- **Milvus（超大规模高维向量相似度检索专用集群）**：
  - 存储对象：切块的高维向量嵌入（Embedding，如 1024 维 / 1536 维）、向量 ID 及轻量用于初筛的标量（如 doc_id、chunk_id）。
  - 强项：千万级至十亿级向量的高吞吐 ANN 计算、硬件加速（GPU / SIMD 指令集）、HNSW / DiskANN 索引、分布式水平线性分片。
2. **选型分水岭：何时 pgvector 足够？何时必须上独立 Milvus？**：
- **选用 pgvector 的黄金窗口（架构极简主义）**：
  - 数据规模：切块向量总数在 **100 万以内**（对应约 2000 本中等文档）；
  - 并发要求：QPS 在 50 以内，单机 8 核 32G 即可承受；
  - 杀手级优势：**零运维成本**，无需额外维护向量数据库集群；可以在同一条 SQL 中原子实现 `JOIN` 用户权限表 + 向量距离排序（`<=>` 算子），杜绝双库一致性难题。
- **必须选用独立 Milvus 的临界条件**：
  - 数据规模：向量量级突破 **500 万 ~ 千万级以上**；
  - 并发要求：高并发生产系统，ANN 检索 QPS $\ge 500$ 且要求 P99 延迟稳定在 15ms 以内；
  - 资源隔离：向量计算极其消耗内存与 CPU，若放在 PostgreSQL 会导致业务 OLTP 事务被挤压卡顿，必须实行物理计算与存储解耦。
3. **核心代码：双库协作架构标准（PG 写元数据 + Milvus 写向量并保持最终一致）**：

```python
from typing import List, Dict, Any
import asyncio
from pymilvus import Collection, connections
import asyncpg

class DualStoreRAGIndexer:
    def __init__(self, pg_pool: asyncpg.Pool, milvus_col: Collection):
        self.pg_pool = pg_pool
        self.milvus_col = milvus_col

    async def insert_chunks_atomic_pattern(self, chunks: List[Dict[str, Any]]):
        """双库协同入库：PG 保证事务落地，Milvus 异步批量构建索引"""
        # 1. 严格时序：首先在 PostgreSQL 开启 ACID 事务写入完整文本与结构化元数据
        async with self.pg_pool.acquire() as conn:
            async with conn.transaction():
                # 写入 PG（包含 parent_id, doc_id, text 等完整上下文）
                records = [
                    (c["chunk_id"], c["doc_id"], c["content"], c["parent_id"])
                    for c in chunks
                ]
                await conn.executemany(
                    """INSERT INTO document_chunks (id, doc_id, content, parent_id)
                       VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO NOTHING;""",
                    records
                )
        
        # 2. PG 事务成功后，提取纯数值向量与对应 ID 插入 Milvus
        milvus_entities = [
            [c["chunk_id"] for c in chunks],       # Primary Key (Int64 / VarChar)
            [c["embedding"] for c in chunks],      # FloatVector 1024 维
            [c["doc_id"] for c in chunks]          # 用于标量过滤的属性
        ]
        
        # 3. 写入 Milvus（在独立线程池中执行防止阻塞）
        try:
            insert_result = await asyncio.to_thread(
                self.milvus_col.insert, milvus_entities
            )
            # 刷盘以确保段（Segment）可见
            await asyncio.to_thread(self.milvus_col.flush)
            print(f"[Milvus 插入成功] 写入 {len(chunks)} 条向量，主键数量: {insert_result.insert_count}")
        except Exception as e:
            # 异常补偿策略：记录失败审计日志，由后台 Worker 异步对齐两库差异
            print(f"[Milvus 插入失败] 必须记录补偿重试队列: {e}")
            raise
```

4. **架构治理与避坑核心**：
- **禁止在 Milvus 存储大文本正文**：Milvus 的 Segment 全部需要加载到内存或内存映射中，把几千字的文本塞进 Milvus 的 scalar 字段会导致极其高昂的 RAM 浪费；
- **分阶段两库对齐**：定期跑离线 Cron 任务比对 `COUNT(pg.chunks) == milvus.num_entities`，避免双库脑裂。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ PostgreSQL 负责业务关系实体、切块元数据、会话历史与 ACID 事务
- ✔️ 数据量在百万以内且需要强事务与复杂 JOIN 权限过滤时，pgvector 是极佳低成本方案
- ✔️ 千万级以上高并发向量计算、原生多模态向量与分布式高弹性扩展场景，必须选用独立 Milvus

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：在使用 pgvector 时，HNSW 索引与 IVFFlat 索引在构建耗时与内存占用上有何本质不同？

- 🎯 **考官意图**：考察 pgvector 核心索引算法原理、构建成本与在线召回率权衡。
- 🛡️ **攻防标准应答**：IVFFlat（倒排文件扁平索引）基于 K-Means 聚类。构建速度极快、内存开销非常小，但必须在数据量稳定后才能建立，且查询召回率较低（容易受边界效应影响）；HNSW（分层导航可小世界图）构建的是多层图结构。构建时间显著更长（慢 10 倍以上），需要消耗巨额内存来维护图邻接表指针，但在查询时无需聚类遍历，而是沿图贪婪跳跃搜索，具备极高的召回率（98%+）和毫秒级超快检索速度。生产建议：数据量在 10 万以下可用 IVFFlat 快速起步，百万级强召回必须选用 HNSW 并预留充足的 `maintenance_work_mem`。
- ⚠️ **避坑要点**：在 pgvector 中建 HNSW 索引如果内存分配不足，会导致极其漫长的磁盘换页甚至建索引失败崩溃。

###### 🎯 追问对决：在 Milvus 中，如何使用 Partition Key 或动态属性标量过滤（Scalar Filtering）来实现高效的多租户物理隔离？

- 🎯 **考官意图**：考察 Milvus 多租户隔离方案性能对比（Collection vs Partition vs Partition Key vs Expr）。
- 🛡️ **攻防标准应答**：Milvus 支持三种多租户方式：第一，每租户建一个 Collection，但 Collection 上限受限且过多会导致元数据（etcd）爆炸；第二，传统 Partition，最多支持 4096 个分区；第三，【工业推荐：Partition Key 机制】：在 Schema 中将 `tenant_id` 指定为 `is_partition_key=True`。Milvus 内部会自动根据哈希将不同租户路由到底层物理 Partition 桶中。检索时只需传入 `expr='tenant_id == "tenant_A"'`，Milvus 的 Proxy 会在查询前执行分区裁剪（Partition Pruning），直接跳过 99% 不相关的底层 Segment 图，实现近乎物理隔离级别的单租户超快响应与百万级租户弹性支撑。
- ⚠️ **避坑要点**：不要在普通标量字段上做无 Partition 优化的全局过滤，这会导致全量向量扫描后再做过滤，速度急剧恶化。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 引入 Milvus 意味着引入了双库架构，必须解决写入时 PG 与 Milvus 之间的两阶段最终一致性
- 🛑 在业务早期切忌为了'技术先进性'盲目上重型向量集群


---
