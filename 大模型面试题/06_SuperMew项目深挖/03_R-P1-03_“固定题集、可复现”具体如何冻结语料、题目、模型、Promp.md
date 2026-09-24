# R-P1-03: “固定题集、可复现”具体如何冻结语料、题目、模型、Prompt、top-k、Rerank 和分块配置？如何复跑同一题？

- **归属项目**：`SuperMew` | **题目类型**：`证据核验题` | **难度等级**：`进阶` | **核心主题**：`评测, RAG`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 通过“43 份语料与 JSONL 题集哈希固化、检索生成全链路超参锁死、独立快照 Partition 隔离、无外部调用的只读对账脚本”四重约束，实现任意单题确定性复跑与产物比对。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

所谓“固定题集、可复现”依靠四大硬性工程约束保证：第一，**语料与题目快照化**：43 份企业复杂文档通过 `backend/indexing/document_loader.py` 入库，输入清单与评测结果落盘为 JSONL 文件，并计算 SHA-256 指纹；第二，**检索管道超参硬绑定**：冻结 Dense BGE-M3 (1024 维) 与 Milvus 原生 BM25 稀疏索引，初检 Top 30 经 RRF ($k=60$) 融合，送入 `Qwen/Qwen3-Reranker-4B` 精排截断至 Top 8；第三，**生成模型确定性推断**：Qwen2.5-72B-Instruct 锁定 `temperature=0.0`、`top_p=1.0`、`seed=42`；第四，**提供只读对账脚本**：`python scripts/summarize_structured_chunking.py` 不发外部请求，直接对已落盘的 baseline 与 structured 结果进行单题与大盘指标比对。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

在 SuperMew 项目中，确保评测结果具备工业级可复现性的具体实现机制如下：

1. **输入与语料资产的指纹冻结**：
- **语料范围**：43 份涵盖技术规范、财务规则与工艺白皮书的企业复杂文档，文档解析与入库后在元数据中记录文件哈希与切块版本号；
- **题目集与清单**：评测集清单存储于 `output/rag-evaluations/enterpriserag/enterpriserag-en-representative-structured-targeted-004/chunking-target-manifest.json`，包含了严格的 SHA-256 校验和；
- **只读快照机制**：评测时使用独立的命名空间与集合，严禁在评测生命周期内执行任何动态 upsert 或后台索引重构。

2. **检索与推理全链路超参锁死**：
- **分块策略对比**：严格对比基线 `recursive_l1_l2_l3`（固定字符递归切分）与结构化版本 `markdown_header_recursive_v1`（标题层级感知与表格边界保护）；
- **初检与重排**：
  - 向量检索：BGE-M3 密集向量（1024 维），余弦相似度；
  - 词法检索：Milvus 原生内置 BM25 稀疏检索；
  - 混合倒数融合：Reciprocal Rank Fusion（RRF），固定参数 $k=60$，提取 Top 30 候选；
  - 交叉重排模型：`Qwen/Qwen3-Reranker-4B`，固定超时与 batch_size，严格截断输出 Top 8；
- **答案生成**：Qwen2.5-72B-Instruct，Prompt 模板固化在 Git 仓库内，强制配置：
  ```python
  generation_params = {
      "temperature": 0.0,
      "top_p": 1.0,
      "seed": 42,
      "max_tokens": 1024,
  }
  ```

3. **单题复跑与只读对账实现机制**：
- 复跑单题时，调用 `scripts/run_rag_evaluation.py` 传入指定 `--case-id`，系统根据固化配置加载历史 Context 进行重跑；
- 聚合对账脚本 `scripts/summarize_structured_chunking.py` 的源码中明确固化了判定常量与输入哈希校验：
  ```python
  # scripts/summarize_structured_chunking.py 核心片段
  EXPECTED_VARIABLE = "document_chunking_strategy"
  EXPECTED_CASE_SET = "analysis"
  EXPECTED_CASE_COUNT = 30

  def _read_jsonl(path: Path) -> list[dict[str, Any]]:
      return [
          json.loads(line)
          for line in path.read_text(encoding="utf-8").splitlines()
          if line.strip()
      ]

  def _sha256(path: Path) -> str:
      return hashlib.sha256(path.read_bytes()).hexdigest()
  ```
- 汇总生成 `structured-chunking-impact-summary.json`，其中 `input_hashes` 字段完整记录 baseline 与 evaluation 的 SHA-256，任何人为篡改均会导致哈希不匹配直接报错中断。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ **只读清单与哈希对账**：43 份文档与 JSONL 题集均计算 SHA-256，评测汇总脚本首先校验 `input_hashes`；
- ✔️ **全链路超参锁死**：Dense 1024 维 + BM25，RRF $k=60$ 选 Top 30，Qwen3-Reranker-4B 截断至 Top 8；
- ✔️ **生成模型参数归零**：`temperature=0.0`、`top_p=1.0`、`seed=42`，Prompt 纳入 Git 版本控制；
- ✔️ **脱机只读复现**：`summarize_structured_chunking.py` 不依赖外部模型调用，可在无网络环境下秒级完成比对复现。

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问 1：大模型即便在 temperature=0 时，由于 GPU 浮点多线程并行累加次序差异，输出仍可能偶发轻微扰动，你们如何做到严格复现？

- 🎯 **考官意图**：考察候选人是否具备真实的工程大模型调试经验，知不知道 GPU 硬件级的浮点非确定性（Non-deterministic floating-point summation）。
- 🛡️ **攻防标准应答**：我们明确区分了“检索确定性”与“生成语义判定”两个层面：1) **检索层严格绝对确定**：向量库索引与 BM25 检索结果通过 chunk_id 进行逐字集合比对（Set Equality），Top 8 召回块 ID 列表必须完全一致；2) **生成层基于事实提取与采分点判别**：评测体系不依赖逐字 exact match 字符串比对，而是使用固化 Prompt 的 LLM-as-a-Judge 与采分点对账脚本（结合人工 Review 队列），即使模型因为 GPU 浮点累加差异改变了个别同义词或助词，只要采分点与核心数值匹配，其 Verdict 依然判定为 Pass。
- ⚠️ **避坑要点**：切勿吹嘘“生成端每一个字 100% 绝对比特级一致”，面试官非常清楚 CUDA 动态调度下的浮点累加不可避免有极微弱抖动。

###### 🎯 追问 2：如果线上复跑发现某个 case 的覆盖率或得分与历史记录不一致，排查的标准流水线是什么？

- 🎯 **考官意图**：考察系统级 Trace 排查与二分调试能力。
- 🛡️ **攻防标准应答**：我们遵循自底向上的四步排查法：1) **校验数据指纹**：检查当前输入语料与题集文件的 SHA-256 是否发生变动；2) **二分检索召回**：检查 Dense/BM25 召回的 Top 30 chunk_id 列表，确认 Milvus 集合是否被意外写入动态数据或索引重建；3) **检查重排打分**：比对 Qwen3-Reranker-4B 对 Top 30 候选块打出的浮点得分及 Top 8 截断切片；4) **检查 Prompt 与依赖版本**：比对生成提示词的 Git Commit ID 以及运行依赖版本。通过这四步，能在 5 分钟内快速将问题定位于“索引漂移”、“权重升级”还是“环境污染”。
- ⚠️ **避坑要点**：不要含糊回答“看日志重新跑一遍”，要展示层次分明的定位链条。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 **不追求生成文本逐字符 Hash 级一致**：生成模型遵循语义对账与采分点判定，以适应浮点运算特性；
- 🛑 **评测环境与线上动态流隔离**：评测集运行于独立的静态快照集合，不复用在线带有动态写入的生产集合。


---
