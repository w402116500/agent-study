# R-G-02: 如果 RAG 找到了正确文件却答不全，会按什么顺序排查解析、分块、召回、精排和回答？

- **归属项目**：`SuperMew` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`RAG, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 按照“文档解析源头（结构/表格/标题完整性）➔ 分块颗粒度与边界（结构化切分 vs 机械截断）➔ 混合初召（Dense BGE-M3 1024-d + Milvus BM25, RRF k=60）➔ 交叉精排（Qwen3-Reranker-4B Top 30➔Top 8）➔ LLM 生成装配与注意力衰减（Lost-in-the-Middle/Prompt约束）”五步严格正向单变量排查。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

在工业级 RAG 落地中，“系统找到了正确文件却答不全”（如指标漏项、表格漏行、对比漏维、前置限制条件缺失）属于最典型的证据链裂化或推理损耗问题，**严禁盲目调换大模型或凭感觉微调 Prompt**。我们必须严格遵循数据流正向流动的五步漏斗排查法：
1. **解析看结构**：原始企业文档（技术规范、合规制度）转 Markdown 后，大章节标题层级、表格行列表头、数学公式与列表是否完整无损；
2. **分块看边界**：切块是否破坏了表格原子性或将强关联上下文截成孤岛（如表头与数据行分离、前提与数值割裂）；
3. **召回看双路**：Dense（BGE-M3 1024-d）与 Sparse（Milvus 原生 BM25）在 Top 30 初筛中，是否因长尾专名或稀疏匹配漏掉了次要证据块；
4. **精排看排序**：交叉重排（Qwen3-Reranker-4B）从 Top 30 截断至 Top 8 时，是否因语义表面相似度偏好而将低重合但高价值的事实切块降级滤除；
5. **生成看位置与推理**：Top 8 上下文装配中是否存在“迷失在中间（Lost-in-the-Middle）”注意力衰减，或 Prompt 缺少结构化提取与穷尽性约束。

在 SuperMew 的 43 份企业复杂语料评测中，高达 60% 以上的“答不全”本质上是在第二步分块层发生断裂，引入 `markdown_header_recursive_v1` 结构化切分直接将全证据覆盖率从 8.33% 提升至 54.17%。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

定位“找到文件却回答残缺”的问题，必须依托可落盘的 Trace 链路做单变量因果排查：

1. **第一步：文档解析层排查（Parsing Verification）**
- **排查目标**：确认原始文档输入解析器后，产出的中间格式（如 Markdown）是否丢失了有效信息。
- **典型失效点**：
  - 多页大表格在跨页处被截断，合并单元格跨页后丢失了主键列或列名表头；
  - 扫描版技术规范或财务附注中的浅色网格被漏解析，导致表格退化为无对齐的字符流；
  - 多级标题体系（`#`, `##`, `###`）未被标准化，导致上下文层级扁平化。
- **验证动作**：比对源文件与 `backend/indexing/document_loader.py` 输出的解析全文。若源文件有 10 行关键技术对比数据，解析文本中只有 6 行，则无需排查后续模块，直接修复上游解析抽取器。

2. **第二步：分块颗粒度与边界排查（Chunking & Context Boundary）**
- **排查目标**：确认解析无误的文档切成 Chunk 时，事实依据是否被腰斩。
- **典型失效点**：
  - 基线 `recursive_l1_l2_l3`（基于字符递归切分，如 2400/1600/800 字符限制）：由于不感知 Markdown 表格语法，常常将一张 30 行大表格硬切成 2~3 个分块。后置切块仅包含数字，丢失了第一行的字段名和前置章节名称，成为“无语义孤岛”；
  - 切块过小（如 300 Token）：单一 Chunk 无法承载完整的因果逻辑链（如“生效前提条件”与“免责条款数值”跨段分布）。
- **验证动作**：检查进入向量库的分块集合。在 SuperMew 中，我们升级为 `markdown_header_recursive_v1`，强制要求表格作为完整原子 Chunk 保存，同时将父级三级标题前缀注入切块 Metadata，使切块自解释性极大增强。

3. **第三步：混合初召漏斗排查（Hybrid Retrieval: Dense + Sparse）**
- **排查目标**：确认包含全部答题要素的切块是否进入了初步候选池（Candidate Pool, Top 30）。
- **典型失效点**：
  - 纯 Dense 向量检索局限：BGE-M3 虽然语义泛化强，但对低频专有型号（如 `X9-PRO-2024`）、精细参数编号往往发生语义泛化漂移；
  - 纯 BM25 稀疏检索局限：缺乏语义关联，当用户 Query 用同义词表述时召回率暴跌；
  - 融合截断损失：Dense 召回 Top 50，BM25 召回 Top 50，经过 RRF（$k=60$）倒数排名融合时，若某项补充证据在两路中均排在第 30~45 名，融合后可能掉出最终候选池 Top 30。
- **验证动作**：打印当前 Query 下 Dense 候选、BM25 候选与 RRF 融合候选清单，检查标注的黄金切块集合是否完整包含在 Top 30 中。

4. **第四步：交叉精排排查（Reranking: Qwen3-Reranker-4B）**
- **排查目标**：确认重排阶段是否将真正的长尾关键证据保留在 Top 8。
- **典型失效点**：
  - 交叉编码重排模型（Cross-Encoder）通过拼接 `[CLS] Query [SEP] Chunk` 进行全注意力计算。它高度敏感于“语义核心匹配度”，往往给宏观结论性切块打出 0.95 高分，而将包含冷门例外条款或细分数据表的切块打出 0.45 低分；
  - 导致截取 Top 8 上下文时，Top 1~4 全是重复性概括，而第 5~8 名被挤占，核心数据行被阻挡在第 9~15 名。
- **验证动作**：输出 Reranker 对 Top 30 切块的重排得分与位次重排差（Delta Rank），确认漏答事实是否在 Top 9~30 中被误杀。

5. **第五步：生成阶段长上下文装配与模型推理排查（Generation & Context Lost）**
- **排查目标**：在 Top 8 完整包含黄金证据的前提下，排查 LLM 为何未能综合输出。
- **典型失效点**：
  - **Lost-in-the-Middle 效应**：8 个切块总 Token 达到 3000~5000，大模型对上下文开头（前 2 块）和结尾（最后 1 块）注意力最高，位于中间位置（第 4、5 块）的表格行容易被注意力衰减直接忽略；
  - **Prompt 引导缺失**：系统 Prompt 没有声明“必须严格核对上下文中的所有条目并逐一列出，如果有多项对比请使用表格输出”，导致模型倾向于短平快的概括回答；
  - **逻辑推理与冲突抑制**：如果切块 2 提到了通用规则，切块 7 提到了特定场景例外，模型若缺乏强大的逻辑对比推理能力，容易产生肯定性偏差，只采纳切块 2 而忽略切块 7。
- **验证动作**：单变量隔离测试——剔除无关切块，仅将黄金切块拼接后直接喂给 Qwen2.5-72B-Instruct。若模型能完美回答，证明根因是上下文噪声或排列位置问题；若依然答不全，证明是 Prompt 约束不足或模型本身体量/微调能力瓶颈。

##### ⭐ 核心关键技术点 (架构图 / 流程树 / 数据流对齐)

```
[原始企业复杂技术文档/规章 (43 份语料)]
         │
         ▼ (Step 1: 文档解析层) ───► 排查点: 表格完整性、跨页连贯性、标题语法
[结构化 Markdown 全文]
         │
         ▼ (Step 2: 文档分块层) ───► 排查点: markdown_header_recursive_v1 表格原子性、上下文割裂
[结构化切块集合 (携带 headers 元数据)]
         │
         ├───► Dense 密集向量 (BGE-M3 1024-d) Top 50 ───┐
         │                                              ├──► (Step 3: 混合初召) RRF (k=60) Top 30
         └───► Milvus 原生 BM25 稀疏检索 Top 50 ────────┘    排查点: 稀疏专名漏召、截断阈值
                                                                 │
                                                                 ▼ (Step 4: 交叉重排)
                                                    Qwen/Qwen3-Reranker-4B (Top 30 ➔ Top 8)
                                                    排查点: 表面字面偏好误杀长尾补充证据
                                                                 │
                                                                 ▼ (Step 5: 生成上下文装配)
                                                    Qwen2.5-72B-Instruct (Lost-in-the-Middle 防御)
                                                    排查点: Prompt 穷尽性约束、长上下文中间注意力衰减
```

排查诊断自动化脚本实现范式（基于 SuperMew 评测工程）：
```python
from typing import List, Dict, Any

def audit_rag_leakage_funnel(
    query: str,
    gold_chunk_ids: List[str],
    pipeline_trace: Dict[str, Any]
) -> Dict[str, Any]:
    """端到端 RAG 漏斗逐层归因诊断函数"""
    dense_ids = [c["id"] for c in pipeline_trace.get("dense_top50", [])]
    bm25_ids = [c["id"] for c in pipeline_trace.get("bm25_top50", [])]
    rrf_ids = [c["id"] for c in pipeline_trace.get("rrf_top30", [])]
    rerank_ids = [c["id"] for c in pipeline_trace.get("rerank_top8", [])]
    final_answer = pipeline_trace.get("generated_answer", "")

    # 1. 验证初召覆盖
    missing_in_dense = [cid for cid in gold_chunk_ids if cid not in dense_ids]
    missing_in_bm25 = [cid for cid in gold_chunk_ids if cid not in bm25_ids]
    missing_in_rrf = [cid for cid in gold_chunk_ids if cid not in rrf_ids]
    
    # 2. 验证精排覆盖
    missing_in_rerank = [cid for cid in gold_chunk_ids if cid not in rerank_ids]

    diagnosis = {
        "gold_chunk_count": len(gold_chunk_ids),
        "stage_failed": "NONE",
        "details": ""
    }

    if missing_in_rrf:
        diagnosis["stage_failed"] = "RETRIEVAL_PRIMARY_DROP"
        diagnosis["details"] = f"黄金切块在初筛Top30阶段丢失: {missing_in_rrf} (Dense漏: {len(missing_in_dense)}, BM25漏: {len(missing_in_bm25)})"
    elif missing_in_rerank:
        diagnosis["stage_failed"] = "RERANKER_DROP"
        diagnosis["details"] = f"初召Top30包含全部证据，但精排Top8截断丢失: {missing_in_rerank}"
    else:
        # Top 8 完整覆盖，排查生成阶段
        diagnosis["stage_failed"] = "GENERATION_LEAK"
        diagnosis["details"] = "Top 8 检索与精排已包含 100% 黄金事实，答不全归因为 LLM 注意力衰减或 Prompt 约束不足"

    return diagnosis
```

##### ❓ 面试官高频追问预判 (攻防反问 / 深水区探测)

###### 🎯 追问 1：如果确认是分块把长表格切断导致答不全，在不重新大动整体分块逻辑的前提下，工程上有哪些低成本热修复手段？
- 🎯 **考官意图**：考察线上工程应急处置与架构拓展能力。
- 🛡️ **攻防标准应答**：
  1. **父子块自动上卷（Parent-Child / Auto-Merging）**：将表格的每几行切为子块（Child Chunk）参与向量匹配与初筛，但在重排或装配生成上下文时，一旦命中该子块，自动将其所属的整张父级大表格或所在完整小节全部补齐塞入上下文；
  2. **元数据表头补全（Header Injection）**：在分块切分器中做轻量拦截，对检测到属于同一张 Markdown 表格的后续分块，强行在切块开头自动补上第一行表头和分隔符，确保每个切块都具备独立自解释的行列语义；
  3. **表格转文字总结索引（Table Summary Chunking）**：为大型表格异步生成一段 200 字的高信息密度文字概括作为检索入口，检索命中后直接通过关联 ID 读取原始完整表格。
- ⚠️ **避坑要点**：不要只说“把 chunk_size 调大”，调大切块会引入无关噪声并降低向量检索的语义聚焦度。

###### 🎯 追问 2：在排查召回层时，如果 Dense 检索到了概括段落，BM25 检索到了数据行，但 RRF 融合后数据行因为排名靠后被 Top 30 截断，你会如何调优 RRF 或融合策略？
- 🎯 **考官意图**：考察对多路召回融合数学机制的理解深度。
- 🛡️ **攻防标准应答**：
  1. **调节平滑常数 $k$**：RRF 公式为 $	ext{Score} = \sum rac{1}{k + r_i}$。默认 $k=60$ 时，第 1 名得分 $0.0164$，第 30 名得分 $0.0111$，衰减非常平缓，排名的区分度不够大。如果调小 $k$（如降至 $k=20$），能大幅放大头部高排名的优势，让在某一路排名极高的细分切块（如 BM25 命中唯一精确型号排第 1）能瞬间跃升入 Top 30；
  2. **加权 RRF（Weighted RRF）**：针对包含明显专有名词、编号的查询意图分类，动态赋予 BM25 稀疏路更高的权重（如 $w_{sparse}=1.5, w_{dense}=1.0$）；
  3. **扩大初召候选池**：将初召阶段截断阈值从 Top 30 放大到 Top 50，因为后续有 4B 级别的交叉重排模型把关，给精排留出足够的候选容错空间。
- ⚠️ **避坑要点**：必须说清楚 RRF 中参数 $k$ 的物理含义（平滑因子）与调大调小的实际数学效果。

###### 🎯 追问 3：在生成排查中，如果证实是典型的“Lost-in-the-Middle”注意力缺陷，SuperMew 或业界有哪些已被验证的工程落地方案？
- 🎯 **考官意图**：考察长上下文工程优化能力。
- 🛡️ **攻防标准应答**：
  1. **上下文倒序/穿插重排（Context Re-ordering / U-Turn 组装）**：不要简单按照重排得分从高到低单向排列，而是将最相关的切块分别放在最前面（Prompt 首部）和最后面（离用户 Query 最近的尾部），把得分较低的补充背景放在中间；
  2. **两阶段 Map-Reduce 抽取**：对于要求全面归纳对比的复杂 Query，先用轻量模型对 Top 8 切块并行执行“证据要素提取（Extract relevant bullet points）”，汇聚为紧凑无噪的事实清单，再喂给 72B 大模型统一生成；
  3. **Prompt 强调约束与思考链引导**：在 System Prompt 中加入强行约束：“必须仔细阅读提供的每一段参考资料，请先列出证据中涉及的所有条目清单，确保无遗漏后再给出综合结论”。
- ⚠️ **避坑要点**：切忌笼统回答“换用 128k 上下文的大模型”，上下文窗口再大也无法根除中间注意力的衰减。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 绝不脱离单变量控制同时修改分块和重排模型，必须逐层固定变量观测指标
- 🛑 绝不在初召阶段为了追求 100% 召回盲目将 Top 候选扩大至数百，精排模型的延迟与计算成本呈线性上升


---
