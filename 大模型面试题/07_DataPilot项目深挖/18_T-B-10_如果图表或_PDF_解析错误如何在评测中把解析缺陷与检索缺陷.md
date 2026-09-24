# T-B-10: 如果图表或 PDF 解析错误，如何在评测中把解析缺陷与检索缺陷分开归因？

- **归属项目**：`SuperMew` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`RAG, 评测, 故障排查`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 查解析中间 Markdown 区分是 MinerU 漏掉还是检索没召回，建立两级错误归因看板。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

当测试集发现某道题答案错误时，系统通过‘先查解析中间态，再查检索候选池’两步完成彻底归因：第一步直接查看 MinerU 产出的 `content.md`，若原文表格在 Markdown 中就已经丢失列或乱码，归因为‘解析缺陷（Parser Fault）’；若 Markdown 中内容完整准确，但在 Top 8 甚至初筛 Top 30 中未命中，则归因为‘检索缺陷（Retrieval Fault）’。两者在评测看板上独立记账统计。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

图表/PDF解析缺陷与检索缺陷的独立归因方案：
1. **业务诊断痛点**：
- 现象：评测集中一道关于“华东区三季度毛利率”的题目回答失败。
- 模糊推诿：算法说是检索没召回，检索说是解析器把表格拆碎了，导致责任链条混乱。

2. **三步归因法（金标准对账法）**：
- **步骤 1：黄金 Markdown 注入（Golden Markdown Oracle）**：
  - 人工对 20 道高价值样本标注完美的纯文本 Markdown，替换掉 MinerU 解析产物。
  - 重新跑分块与检索：若依然无法召回，则归因为【纯检索缺陷】（分块截断、BM25 词根未匹配、向量相似度低）。
- **步骤 2：解析包原文比对（Text Preservation Check）**：
  - 直接在 MinerU 生成的 `content.md` 中用正则或精确字符串搜索 Ground Truth 关键事实。
  - 若 `content.md` 中根本不存在该数值（或由于 OCR 错误变为乱码），则 100% 归因为【解析器缺陷】。
- **步骤 3：切块边界截断检测（Chunk Boundary Check）**：
  - 事实在 `content.md` 中存在，但在分割出来的 chunk 中被跨块切成两半，归因为【切分边界缺陷】。

3. **归因看板量化与闭环改进**：
- 生产实践中引入标签化归因：将每次评测的 Bad Case 自动分类归入 `PARSE_OCR_ERR`、`CHUNK_CUT_ERR`、`RETRIEVAL_MISS`、`RERANK_DROP`。
- 只有建立客观数据漏斗，才能指导各专项优化投入产出比（ROI）。
3. **核心代码：双轨对账归因器（区分 Markdown 解析缺陷与向量/BM25 检索缺陷）**：

```python
from typing import Dict, List, Optional

class RetrievalErrorAttributor:
    def __init__(self, raw_retriever, golden_store: Dict[str, str]):
        self.retriever = raw_retriever
        self.golden_store = golden_store # 预先人工校准的 20 道题完美黄金 Markdown

    def diagnose_failure(
        self, 
        query_id: str, 
        query: str, 
        target_chunk_id: str
    ) -> Dict[str, str]:
        """独立归因：到底是 PDF 解析破损，还是分块检索算法失误"""
        # 1. 跑原始检索流程（使用 MinerU 解析出的切块）
        raw_hits = self.retriever.search(query, top_k=8)
        hit_ids = [h["chunk_id"] for h in raw_hits]
        
        if target_chunk_id in hit_ids:
            return {"status": "SUCCESS", "culprit": "NONE"}
            
        # 2. 发生未召回，启动【黄金 Markdown 对账】
        golden_md = self.golden_store.get(query_id)
        if not golden_md:
            return {"status": "FAILED", "culprit": "UNKNOWN", "reason": "缺少黄金对账样本"}
            
        # 3. 如果把切块换成完美的 golden_md，检索算法能否命中？
        oracle_hit = self.retriever.search_against_oracle(query, golden_md)
        if oracle_hit:
            # 算法在标准文本上能命中，但在真实切块上未命中 -> 100% 归因为解析器切损表格
            return {
                "status": "FAILED",
                "culprit": "PARSER_DEFECT",
                "detail": "MinerU 表格切分换行破损，导致跨行数值脱节"
            }
        else:
            # 算法在完美黄金文本上也漏检 -> 归因为检索算法召回缺陷
            return {
                "status": "FAILED", 
                "culprit": "RETRIEVAL_DEFECT",
                "detail": "BM25 专有名词分词脱靶或 Dense 向量余弦相似度过低"
            }
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 根据 MinerU 中间态 content.md 是否包含黄金事实，一秒切分‘解析坏了’还是‘检索丢了’
- ✔️ 结合初筛 Top 30 与精排 Top 8 的 Trace 日志，细分初筛漏召回还是精排误过滤
- ✔️ 双轨统计看板防止算法团队背上上游文档 OCR 扫描质量的‘黑锅’，界定清晰工程边界

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果在解析端发现有些印章遮盖的文字 OCR 识别错误，算法团队没有模型训练算力如何应急？

- 🎯 **考官意图**：考察资源受限条件下的工程折中与补偿机制。
- 🛡️ **攻防标准应答**：工程补偿三招：1) 引入预处理图像去噪滤镜（如 OpenCV 颜色空间分离，滤除红色公章图层后再走 OCR）；2) 在文档上传时提供人工校验界面，对关键元数据允许运营补录修正；3) 结合上下文同义词与 BM25 模糊容错匹配，补偿 OCR 单字识别偏差。
- ⚠️ **避坑要点**：不要轻易承诺重训多模态大模型，那是高成本动作，工程链路优化必须优先。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 归因自动化仅覆盖文本和 Markdown 字符匹配，图表内的矢量趋势图尚需人工介入研判
- 🛑 解析产物追踪依赖中间包（Parsed Bundle）未被过期清理


---


### 模块八：DataPilot SQL 安全与 AST 防护 (SQL Guard & AST Interception, T-C-01 ~ T-C-10)
