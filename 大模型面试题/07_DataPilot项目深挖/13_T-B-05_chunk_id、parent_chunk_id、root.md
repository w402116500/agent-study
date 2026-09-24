# T-B-05: `chunk_id`、`parent_chunk_id`、`root_chunk_id`、`chunk_idx` 各自用于什么？哪些字段必须进入检索记录？

- **归属项目**：`SuperMew` | **题目类型**：`简单题` | **难度等级**：`基础` | **核心主题**：`RAG, 系统设计, 数据建模`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> chunk_id 唯一标识，parent/root 维系树状归属，idx 记录物理位次；向量库仅存 L3 检索记录。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

每个分块维护明确的坐标元数据：`chunk_id` 是块的全局 UUID；`parent_chunk_id` 指向父级（L3 指向 L2，L2 指向 L1）；`root_chunk_id` 统一锚定文档级根块（L1）；`chunk_idx` 记录在全文中的物理顺序编号。在 Milvus 中，必须进入检索记录的字段包括 `chunk_id`、`vector`、`parent_chunk_id`、`root_chunk_id`、`doc_id` 和文本摘要，以便检索命中后直接在内存中执行父级归类并关联回源。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

切块标识体系（chunk_id / parent / root / idx）与检索元数据精简原则：
1. **四大 ID 职责划分**：
- `chunk_id`：叶子节点（L3）全局唯一主键，命名格式 `{doc_id}_{md5(content)[:8]}_{idx}`，用于 Milvus 向量主键与 BM25 文档键。
- `parent_chunk_id`：中间父块（L2）指针，用于检索命中后做父文档上下文折叠与召回扩展。
- `root_chunk_id`：根章节（L1）指针，用于判断多条召回是否属于同一大章节，做章节级别的多样性去重（Diversity Rerank）。
- `chunk_idx`：在当前文档内的绝对时间轴/物理排版序号（0, 1, 2, ...），用于多块拼接时的顺序还原。

2. **核心代码：检索记录（Retrieval Record）元数据投影过滤**：

```python
from pydantic import BaseModel, Field
from typing import Optional

class MilvusIndexPayload(BaseModel):
    """
    精简元数据载荷：
    严禁把原始整篇 PDF 二进制、大段冗余日志塞入向量库标量字段！
    """
    chunk_id: str = Field(..., description="向量记录唯一ID")
    doc_id: str = Field(..., description="所属原始文件ID，用于权限过滤与文档物理删除")
    parent_chunk_id: str = Field(..., description="父级 L2 块 ID，用于后处理展开")
    root_chunk_id: str = Field(..., description="L1 章节 ID，用于多源去重")
    chunk_idx: int = Field(..., description="全局物理序号，用于相邻窗口上下文扩展 (+/- 1)")
    chunk_level: int = Field(default=3, description="切块层级，通常为3")
    content: str = Field(..., description="供大模型阅读的正文文本（800字）")
    # 标量过滤属性（用于高效 Pre-filtering）
    department_id: str = Field(..., description="租户或部门权限隔离ID")
    version_id: str = Field(..., description="文件版本号，支持蓝绿切换")

def prepare_milvus_record(raw_chunk: dict) -> dict:
    """过滤清洗，剔除无效富媒体引用与冗余对象，减小索引存储体积"""
    payload = MilvusIndexPayload(**raw_chunk)
    return payload.model_dump()
```

3. **进入检索记录的红线与取舍**：
- 必须进入：`chunk_id`、`doc_id`、`parent_chunk_id`、`chunk_idx`、`content`、权限与版本标量。
- 坚决剔除：原始富文档 AST 坐标框字典、Base64 图片流、临时文件路径。这些内容存储在 MinIO 解析包中，只在前端用户点击“定位到原文档截图”时按需点查，绝不污染高频热检索存储。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ chunk_id 是全局定位凭证，parent/root 维系两级上卷树谱，chunk_idx 保障拼接语序不变
- ✔️ Milvus 存 L3 向量与拓扑关系元数据，支持内存中直接完成 Auto-merging 决策
- ✔️ 正文与父块正文下沉至 PG 与 Redis，降低向量库内存开销，遵循读写分离架构

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：当命中多个连续的 chunk 时，前端如何利用 chunk_idx 进行优雅合并？

- 🎯 **考官意图**：考察连续命中切块的合并算法与上下文去重细节。
- 🛡️ **攻防标准应答**：按照 `(doc_id, parent_chunk_id)` 分组后，检查 `chunk_idx` 差值是否为 1。如果是连续自然段，直接以换行符合并两者的 `content` 并去除 overlap 重叠词，合并为一个大引用卡片，大幅减少 Prompt 拼接时的 Token 浪费。
- ⚠️ **避坑要点**：不要把所有命中的 chunk 无脑并列展示，碎片化引用会使大模型注意力分散并产生幻觉。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 chunk 树深度严格限制为 3 层（L1->L2->L3），不引入无限递归的通用树结构
- 🛑 Milvus 集合设置动态 Schema 限制，仅持久化必选元数据列


---
