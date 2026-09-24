# R-P3-03: 提到 L1/L2/L3；父块 ID、叶子块 ID 和实际存储位置怎样关联？

- **归属项目**：`SuperMew` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`RAG, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 叶子 L3 存入 Milvus 向量库并外键关联；父级 L1/L2 富文本保存在 PostgreSQL 并由 Redis 提供只读高速缓存。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

关联与存储方案非常清晰：每个切出的分块拥有确定性 ID（如 `doc_uuid_l3_05`），其元数据中携带 `parent_chunk_id`（指向 L2）与 `root_chunk_id`（指向 L1）。在物理存储上，只有具备最高语义密度的 L3 写入 Milvus 向量库；而 L1 与 L2 由于体积大且无需向量化，完整正文保存在 PostgreSQL 的 `document_chunks` 关系表中；同时利用 Redis 缓存高频被命中的父块正文，检索命中 L3 后以 O(1) 复杂度通过外键拼装完整父级段落。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

L1/L2/L3 父子层级切分与多级存储映射架构：
1. **三层分块规范与业务职责**：
- **L3 叶子切块（800 字）**：直接切片单元，保留最精准的局部语义。存入 Milvus 向量库（含 BGE-M3 Dense 与 BM25 稀疏索引），用于高敏度匹配。
- **L2 节级父块（1600 字）**：涵盖一个完整业务段落或小节。存储在 PostgreSQL 关系库与 Redis 缓存。
- **L1 章级根块（2400 字）**：涵盖完整表格（如跨页财务表）或整个章结构。存储在 PostgreSQL，当同父块命中数超限时触发上卷替换。

2. **存储映射与外键关联设计**：
- Milvus 只保存 L3 的 `chunk_id`, `parent_chunk_id`, `root_chunk_id` 和精简向量；
- PostgreSQL 的 `document_chunks` 表保存全文富文本 Markdown、图片链接与层级关系；
- Redis 以 `chunk:parent:{parent_id}` 缓存热点父块，TTL 设为 24 小时。

3. **核心代码：分级上卷与缓存加载实现（含逐行注释）**：
```python
from typing import List, Dict, Set
from collections import defaultdict
import redis.asyncio as aioredis

class HierarchyResolver:
    """父子层级映射与 Auto-merging 上卷解析器"""
    def __init__(self, pg_pool, redis_client: aioredis.Redis, merge_threshold: int = 2):
        self.pg_pool = pg_pool
        self.redis = redis_client
        self.merge_threshold = merge_threshold  # 命中 >=2 个同父块即触发上卷

    async def resolve_and_auto_merge(self, leaf_results: List[dict]) -> List[dict]:
        # 1. 统计各个 parent_chunk_id 命中的子切块数量
        parent_hits = defaultdict(list)
        for doc in leaf_results:
            pid = doc.get("parent_chunk_id")
            if pid:
                parent_hits[pid].append(doc)

        final_context = []
        absorbed_leaves: Set[str] = set()

        # 2. 识别满足上卷阈值的父切块
        for pid, leaves in parent_hits.items():
            if len(leaves) >= self.merge_threshold:
                # 命中 >= 2 个，标记吸收子切块，拉取完整父块
                absorbed_leaves.update(l["chunk_id"] for l in leaves)
                parent_doc = await self._fetch_parent_chunk(pid)
                if parent_doc:
                    final_context.append(parent_doc)

        # 3. 保留未被父块吸收的孤立叶子切块
        for doc in leaf_results:
            if doc["chunk_id"] not in absorbed_leaves:
                final_context.append(doc)
        return final_context

    async def _fetch_parent_chunk(self, parent_id: str) -> dict:
        # 优先读 Redis 缓存，穿透再读 PostgreSQL
        cached = await self.redis.get(f"chunk:parent:{parent_id}")
        if cached:
            return json.loads(cached)
        async with self.pg_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT chunk_id, content, metadata FROM document_chunks WHERE chunk_id = $1", parent_id)
            if row:
                doc = {"chunk_id": row["chunk_id"], "text": row["content"], "metadata": row["metadata"]}
                await self.redis.setex(f"chunk:parent:{parent_id}", 86400, json.dumps(doc))
                return doc
        return None
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 确定性层级 ID 显式维护 parent_chunk_id 与 root_chunk_id 指针
- ✔️ Milvus 仅存 L3 向量与引用外键，节约昂贵内存
- ✔️ PostgreSQL 持久化完整大块文本，Redis 充当父块热点缓存

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：当文档被删除或更新时，PostgreSQL、Redis 与 Milvus 如何保证三者同步清理？

- 🎯 **考官意图**：考察分布式多级存储与缓存一致性设计的成熟度。
- 🛡️ **攻防标准应答**：采用'先更数据库，再删缓存，异步清理向量库'的最终一致性模式：1) 开启 PG 事务标记文档为 DELETED；2) 发送事件让 Redis 批量删除相关 parent_chunk 缓存键；3) 异步任务根据 doc_id 在 Milvus 中执行标量条件删除（`expr="doc_id == 'xxx'"`），若失败则依赖重试队列保证最终清理。
- ⚠️ **避坑要点**：切忌回答'用分布式两阶段提交 2PC'，异构向量存储与缓存系统根本不支持 XA 事务，务实的工程方案是事件驱动的软删除与最终一致性。

###### 🎯 追问对决：如果一个父块下有 10 个子块，命中几个子块才判定拉取父块？

- 🎯 **考官意图**：考察 Auto-merging 上卷启发式阈值调优细节。
- 🛡️ **攻防标准应答**：生产阈值设定为 `>= 2` 个叶子切块。在 300 题分析集上的单变量实验表明：阈值设为 1 会导致父块上卷过激，大量无关上下文冲淡了精排焦点；阈值设为 3 则对跨页大表格召回率提升有限；设定为 2 能精准平衡上下文丰富度与噪声抑制。
- ⚠️ **避坑要点**：不要张口说'50%'或'命中全部'，子块数量动态变化，固定比例往往在长文档中导致上卷永远无法触发。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 L3 到 L2 的关联是一对多强树形拓扑，暂不支持跨文档的网状图谱引用
- 🛑 Redis 缓存若击穿，PostgreSQL 的单表索引查询需保持毫秒级吞吐


---
