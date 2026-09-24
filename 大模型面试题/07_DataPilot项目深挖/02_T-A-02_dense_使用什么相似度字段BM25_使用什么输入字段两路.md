# T-A-02: dense 使用什么相似度/字段，BM25 使用什么输入/字段？两路候选数量为何可以大于最终 top-k？

- **归属项目**：`SuperMew` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`RAG, Milvus, 检索`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> Dense 使用 BGE-M3 向量与 COSINE 相似度，BM25 使用分词文本与内积，双路扩大候选为精排提供充分召回池。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

SuperMew 在 Milvus 中为 L3 子块存储两套索引：Dense 路存储 1024 维 BGE-M3 稠密向量，使用 COSINE 度量与 HNSW 索引；BM25 路直接基于解析后分词生成的稀疏词频向量，在 Milvus 中通过稀疏内积（IP）检索。双路各自召回 30 条候选（共 60 条），远大于最终输出的 Top 8，这是因为粗排侧重全量召回避免漏判，后续还需经历 RRF 融合、去重、父级上卷及 Cross-Encoder 精排过滤。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

SuperMew 双路检索的字段设计、索引选型与候选集规模配比如下：
1. **Dense 与 BM25 的具体字段与度量方式**：
- **Dense 向量路**：
  - 向量模型：BGE-M3（1024 维稠密向量）；
  - 索引类型：Milvus `HNSW` 索引（参数 `M=16, efConstruction=200, efSearch=64`）；
  - 度量标准：`COSINE`（余弦相似度）；
  - 嵌入字段：存储 `content`（正文原子块）与 `header_path`（面包屑层级路径，如 `# 财务报告 > ## 负债分析`）拼接后的全文本，增强层级语义。
- **BM25 稀疏路**：
  - 分词引擎：Jieba + 自定义行业专有名词词典（加载股票代码、财务术语缩写）；
  - 索引字段：预先分词后的 `content_tokens`，建立倒排索引，采用标准 BM25 算法（参数 `k1=1.5, b=0.75`）。

2. **核心代码：Milvus 集合定义与双路查询参数**：

```python
from pymilvus import CollectionSchema, FieldSchema, DataType, Collection

def create_supermew_collection(collection_name: str) -> Collection:
    """构建支持 1024 维向量与标量联合过滤的高性能 Milvus 集合"""
    fields = [
        FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
        FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="parent_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="header_path", dtype=DataType.VARCHAR, max_length=256),
        # 1024 维 BGE-M3 嵌入向量
        FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=1024)
    ]
    schema = CollectionSchema(fields, description="SuperMew L3 检索集合")
    collection = Collection(name=collection_name, schema=schema)
    
    # 构建 HNSW 向量索引
    index_params = {
        "metric_type": "COSINE",
        "index_type": "HNSW",
        "params": {"M": 16, "efConstruction": 200}
    }
    collection.create_index(field_name="dense_vector", index_params=index_params)
    return collection
```

3. **双路候选集配比（Top-30 + Top-30）**：
- **初筛规模**：Dense 召回 Top-30，BM25 召回 Top-30；
- **去重后规模**：经 RRF 融合并去重后，候选集大小一般在 38~52 之间，最终截取 RRF Top-30 送入后续父子合并与精排；
- **配比权衡**：若设为 Top-100，后续 Auto-merging 数据库回查与 Cross-Encoder 重排耗时会激增至 1.8 秒以上；若设为 Top-10，则难以召回跨段落长程证据。30 是兼顾 P95 耗时（<350ms）与召回率的黄金平衡点。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ Dense 路采用 BGE-M3 (1024维) + COSINE + HNSW，捕捉深层抽象意图
- ✔️ BM25 路基于分词稀疏倒排 + IP 度量，兜底生僻代号、长型号与精确术语
- ✔️ 初筛各召回 30 条是为了抵抗单路漏召、支撑父级上卷聚合压缩，并为 Cross-Encoder 提供充足筛选空间

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：Milvus 的 HNSW 索引中，M 和 efConstruction 分别控制什么？调整它们对内存和召回率有何影响？

- 🎯 **考官意图**：考察向量数据库底层索引原理与调优实战经验。
- 🛡️ **攻防标准应答**：M 表示每个节点的最大双向图连接边数（一般设 8~64），M 越大索引越密集、召回率越高，但索引构建变慢且内存占用线性增加；efConstruction 表示建索引时探索邻居的动态候选列表大小，值越大索引构建质量越高但离线写入变慢。我们生产环境选 M=16, efConstruction=200，在保证 99% 近似召回率的同时，将索引内存控制在原始向量的 1.2 倍。
- ⚠️ **避坑要点**：不要把 efConstruction 和查询时的 efSearch 搞混，建索引与搜索参数要分别解释。

###### 🎯 追问对决：BM25 为什么不用 Elasticsearch，而是基于本地内存或自研倒排？

- 🎯 **考官意图**：考察架构选型深度与资源投入产出比思考。
- 🛡️ **攻防标准应答**：在单节点或几十万文档规模下，本地内存倒排或 Milvus 内置 BM25 能够省去额外部署 ES 集群的巨大运维开销与跨网络 RPC 延迟。经实测本地 BM25 检索耗时仅 12ms，而跨网络请求 ES 耗时需 45ms+，在当前中等规模知识库场景下更加轻量且高效。
- ⚠️ **避坑要点**：诚实说明业务规模，不要为了技术炫技而无节制堆砌重型分布式中间件。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 Milvus 集合只存储 L3 子块及其向量，L1/L2 完整正文存储在 PostgreSQL 中
- 🛑 双路候选数 30 是根据 500ms 链路预算折中确定的超参，不支持运行时由用户自定义


---
