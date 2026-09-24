# T-G-04: 如果把 Milvus BM25 换成 Elasticsearch，如何保持可插拔和评测可比？

- **归属项目**：`SuperMew` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`搜索引擎, Milvus, Elasticsearch, 评测对比`
- **可信级别**：项目事实 / 架构设计

> 💡 **一句话速记结论**：
> 抽象 BaseRetriever 策略接口解耦底层实现，冻结测试集与指标打分脚本保证评测环境严格可比。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

将 Milvus BM25 换成 Elasticsearch，保持系统可插拔的核心是'接口适配器模式'，保持评测可比的核心是'评测环境与测试集的完全冻结'。在代码层，定义抽象的 `BaseSparseRetriever` 接口，暴露统一的 `search(query, top_k, filter_expr)` 方法，ES 与 Milvus 仅是不同适配器实现；在评测层，使用完全相同的文本切块分词结果、固定的黄金评测集（Ground Truth Q&A），在相同的 Top-k 截断和 RRF 参数下对比 Hit@5、MRR 与延迟，确保唯一变量仅为底层检索引擎。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

将 Milvus BM25 替换为 Elasticsearch 时的可插拔接口抽象与评测可比性方案：
1. **可插拔架构设计原则（SPI / Interface Decoupling）**：
- 严格遵循依赖倒置原则（DIP）：检索核心调度层绝不直接调用具体客户端 SDK，而是依赖统一的抽象基类 `BaseSparseRetriever`。
- 保证随时可以通过配置文件配置 `sparse_retriever_type: "elasticsearch" | "milvus_bm25"` 进行秒级无缝切换。

2. **核心代码：标准可插拔接口与适配器实现**：

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseSparseRetriever(ABC):
    @abstractmethod
    async def search(self, query: str, limit: int = 30) -> List[Dict[str, Any]]:
        """必须统一输出归一化格式: [{'chunk_id': '...', 'score': 0.85, 'content': '...'}]"""
        pass

class ElasticsearchSparseRetriever(BaseSparseRetriever):
    def __init__(self, es_client, index_name: str):
        self.es = es_client
        self.index_name = index_name

    async def search(self, query: str, limit: int = 30) -> List[Dict[str, Any]]:
        # 执行标准 ES BM25 查询并归一化输出
        res = await self.es.search(index=self.index_name, body={
            "query": {"match": {"content": query}},
            "size": limit
        })
        return [{"chunk_id": hit["_id"], "score": hit["_score"], "content": hit["_source"]["content"]} for hit in res["hits"]["hits"]]
```

3. **如何保证评测可比性（Evaluation Equivalence）**：
- **分词词典完全对齐**：必须保证 Elasticsearch 与 Milvus BM25 采用完全一致的中文分词器（如同版本的 IK-MaxWord / Jieba）与完全一致的停用词表；
- **分块数据集冻结**：切分产生的文本块必须完全一致；
- **评测指标全闭环**：在相同的 300 analysis 测试集上，比对 Hit Rate@3 与 MRR。只有底层分词一致，对比两者的打分与性能差异才具有科学可比性。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 通过 Retriever 抽象基类隔离底层驱动，依靠工厂模式与配置中心实现动态可插拔
- ✔️ 分词算法与分词词典必须严格对齐，避免分词差异污染引擎本体的召回表现
- ✔️ 冻结语料切块、评测集、超参（k1, b, RRF k=60）及 Rerank 环节，严格隔离唯一变量

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：Elasticsearch 的原生 BM25 得分通常是 10 几甚至几十，而 Milvus 返回的是归一化得分，RRF 融合时会受影响吗？

- 🎯 **考官意图**：考察 RRF 倒数排名算法对绝对得分尺度的免疫特性。
- 🛡️ **攻防标准应答**：完全零影响！这就是选用 RRF（倒数排名融合）而非直接按分数相加的精妙之处：RRF 算法只关心候选文档在列表中的相对位次（Rank 1st, 2nd, 3rd），彻底消除了 ES 原生打分与 Milvus 打分的绝对数值尺度差异，天然具备跨引擎可插拔性！
- ⚠️ **避坑要点**：不要说需要先做 Min-Max 归一化，RRF 本身就是针对排名的无量纲算法，不需要做复杂归一化。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 当前 SuperMew 选型 Milvus BM25 是为了统一降低单机与集群维护复杂度，避免维护双库一致性
- 🛑 ES 替换后需要引入双写保障机制或 CDC 增量同步管道


---
