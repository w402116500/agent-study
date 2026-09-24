# R-P2-07: 说“建立评测闭环”；题集如何标注 expected docs/facts，失败归因怎样进入下一轮实验？

- **归属项目**：`SuperMew` | **题目类型**：`证据核验题` | **难度等级**：`高难` | **核心主题**：`评测, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 构建 300 题分析集与 200 题留存验证集，双盲标注 Expected Facts，将失败自动化归因到解析、检索或生成层。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

我们建立的评测闭环绝非‘跑几道题肉眼看一看’，而是工程化数据驱动闭环：先从真实企业技术咨询日志中抽样清洗出 500 道真实题目，严格划分为 300 道‘研发探索分析集’和 200 道‘双盲留存验证集’；每道题人工标注 Expected Docs 与核心黄金事实清单。通过流水线 Trace 将失败归因为‘解析缺失’、‘召回落空’、‘排序靠后’还是‘模型幻觉’。每一轮迭代只改动单一模块并重跑测试，只有在 300 题取得指标提升且 200 题验证集无泛化衰退时，代码才获准合并。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

建立严密评测闭环体系的完整实施步骤如下：
1. **评测题集构建与严密切分（300 analysis 分析集 vs 200 validation 盲测集）**：
- **来源与真实度**：从企业真实技术支持工单、财报审计答疑与业务分析高频场景中抽样清洗，保证覆盖表格计算、跨段推理与专有名词查询；
- **防数据穿越红线**：全量 500 道题由测试组在系统开发前完成双盲标注；60%（300 道）作为公开分析集用于调参，40%（200 道）作为冷冻盲测集存入受保护私有目录，开发人员与算法优化脚本在调优期间完全不可见，只在发版前执行一次性盲测。

2. **多层黄金标注结构（Golden Annotation Schema）**：
- `expected_chunk_ids`：该问题必须召回的所有关键证据切块 ID（用于算 Retrieval Recall 与 Evidence Coverage）；
- `expected_facts`：不可妥协的核心事实点列表（如 `["扭矩: 45N·m", "误差范围: ±1.5%"]`，用于验证回答忠实度）；
- `gold_sql`：对于 DataPilot 数据题，标注经过 DBA 审定的基准标准查询语句。

3. **核心代码：自动化三层归因诊断引擎（Failure Attribution Engine）**：
```python
from typing import Dict, List
import json

class RAGAttributionEngine:
    """自动化失败归因器：精准区分上游解析缺陷、检索召回缺陷或下游模型幻觉"""
    def __init__(self, eval_dataset_path: str):
        with open(eval_dataset_path, 'r', encoding='utf-8') as f:
            self.cases = json.load(f)

    def attribute_failure(self, case_id: str, retrieved_chunk_ids: List[str], generated_answer: str) -> str:
        case = next(c for c in self.cases if c["id"] == case_id)
        expected_ids = set(case["expected_chunk_ids"])
        expected_facts = case["expected_facts"]
        retrieved_set = set(retrieved_chunk_ids)

        # 1. 检查检索层证据覆盖度
        missing_evidence = expected_ids - retrieved_set
        if missing_evidence:
            # 进一步区分是解析层未建索引，还是检索排位靠后掉出 top-k
            return f"RETRIEVAL_FAILURE: 关键证据缺失 {missing_evidence}，需排查双路检索或分块"

        # 2. 证据已完全召回，检查大模型回答是否忠实覆盖核心事实
        missing_facts = [fact for fact in expected_facts if fact not in generated_answer]
        if missing_facts:
            return f"GENERATION_FAILURE: 证据已充足但模型丢失事实 {missing_facts}，属模型理解或 Prompt 提示不足"

        return "SUCCESS: 证据完全覆盖且事实校验通过"
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 300 道分析集调优与 200 道留存集验证严格隔离防过拟合
- ✔️ 标注精细到 Expected Docs 路径与客观 Expected Facts 黄金元
- ✔️ 四层自动化归因将失败清晰定位到解析、召回、精排或大模型生成

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果某道题大模型回答的字面表述与 expected_facts 不完全一致，但语义相同，评测如何避免被判为失败？

- 🎯 **考官意图**：考察 LLM-as-a-Judge 评测设计、语义等价性判定与 Prompt 约束技巧。
- 🛡️ **攻防标准应答**：我们采用基于 Qwen2.5-72B 的 LLM-as-a-Judge 判定方案，而不是死板的字符串精确匹配：评测 Prompt 输入标准三元组（用户问题、Golden Facts、模型输出），要求 Judge 仅从语义包含关系判断每个 Fact 是否被无歧义表达；同时设置 Temperature=0.0，要求 Judge 必须在 JSON 中为判定为 False 的项输出逐词引用理由，保证评测的确定性与可复核性。
- ⚠️ **避坑要点**：不要回答'直接用 Python in 包含判断'或'用 BLEU/ROUGE'，那套传统指标在长文本大模型语义评测上准确率极差。

###### 🎯 追问对决：当归因结果显示为 RETRIEVAL_FAILURE 时，团队下一步的具体排查流程是什么？

- 🎯 **考官意图**：考察问题定位的实战工程经验与链路式排查逻辑。
- 🛡️ **攻防标准应答**：排查流程严格分为三步：1) 查索引库元数据：确认缺失的黄金内容是否被 MinerU 正确解析为 Markdown，且确实切分出了对应的 Chunk ID；如果连 Chunk 都没生成，问题在解析/分块层；2) 查初筛排位：打印 Dense 路和 BM25 路各自的 Top-100 召回清单，看该切块是未被检出，还是排在第 40 名导致在 Top-30 截断时被抛弃；3) 若排位靠后，则排查是否是分词未切出关键词，或是 Reranker 排序模型将其错误降权。
- ⚠️ **避坑要点**：必须体现由浅入深的排查层次（解析 -> 索引 -> 初筛排位 -> 精排打分），切忌一上来就盲目改提示词。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 自动化归因脚本基于规则与轻量判定模型，边缘情况仍需人工二次核实
- 🛑 评测集仅代表企业技术与设备领域语料分布，无法等同于开放域问答能力


---
