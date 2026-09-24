# T-F-02: 一次分块策略变更导致分数下降，如何用固定题集、逐题 trace 和单变量对照定位原因？

- **归属项目**：`SuperMew` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`RAG调试, 单变量实验, Trace归因`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 固定 300 道基准题集与模型参数，仅变动分块切分，对比逐题 Trace 定位跨页表格断裂。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

当分块策略调整导致分数下降时，必须严格锁死固定测试集（如 300 道标准题）、Embedding/Rerank 模型与 LLM Prompt，仅以分块策略为唯一变量。通过比较两次实验的逐题 Trace JSON，比对召回的分块 ID、文本片段与 MRR 变化。通过差异对比，能迅速发现是新分块在换行截断时破坏了跨页表格表头，导致上下文信息失真。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

分块策略变更导致评测指标下降时的单变量对照与 Trace 定位流程：
1. **真实排障场景**：
- 现象：将切块策略从 L1/L2/L3 调整为固定 500 Token 切分后，300 analysis 集上的通过率突然从 69.3% 暴跌至 58.1%。
- 严谨排障原则：严禁拍脑袋瞎改其他参数，必须实施**三步单变量回溯法**。

2. **核心代码：逐题 Trace Diff 与单变量因果归因**：

```python
import json

def diff_evaluation_traces(run_a_path: str, run_b_path: str):
    """
    对比两次评测的逐题明细 Trace:
    Run A: 基准版本 (旧分块)
    Run B: 劣化版本 (新分块)
    """
    with open(run_a_path, 'r', encoding='utf-8') as f:
        traces_a = {item["qid"]: item for item in json.load(f)}
    with open(run_b_path, 'r', encoding='utf-8') as f:
        traces_b = {item["qid"]: item for item in json.load(f)}

    regression_cases = []
    for qid, record_a in traces_a.items():
        record_b = traces_b.get(qid)
        # 筛选在 A 中成功但在 B 中失败的倒退用例（Regression Case）
        if record_a["passed"] and not record_b["passed"]:
            regression_cases.append({
                "qid": qid,
                "gold_evidence": record_a["ground_truth"],
                "retrieved_in_a": record_a["retrieved_chunks"],
                "retrieved_in_b": record_b["retrieved_chunks"],
                "answer_b": record_b["final_answer"]
            })

    print(f"共发现 {len(regression_cases)} 个倒退 Bad Case，开始深入分析切块边界...")
    return regression_cases
```

3. **根因定位闭环（单变量控制）**：
- **步骤 1：固定题集与随机种子**：严格在同一个 300 题集上运行，LLM 的 Temperature=0 保持一致；
- **步骤 2：切块边界可视化比对**：将倒退题目在 Run A 与 Run B 中的命中切块高亮对比，通常会发现固定 500 Token 把财务三线表格的表头与明细数据拦腰截断，导致语义丢失；
- **步骤 3：单变量证伪**：回滚分块策略，仅针对表格保留结构感知，指标立即回升，完成科学因果闭环。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 严格锁定测试集、检索器参数、模型 Prompt 与温度，保证分块为唯一自变量
- ✔️ 通过负向样本过滤脚本，秒级定位在两次运行中结果恶化的具体题目
- ✔️ 对比 Trace 中分块原文与表头上下文，直接归因切分造成的语义截断

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果同时修改了分块长度和 Reranker 模型，发现总分提升了 2%，这种实验可以算成功吗？

- 🎯 **考官意图**：考察工程科学素养与控制变量实验规范。
- 🛡️ **攻防标准应答**：不能算成功，这是典型的多变量混淆实验！无法判定这 2% 是由于分块变好带来的，还是由于 Reranker 带来的（甚至可能分块其实劣化了，只是被强力 Reranker 掩盖了）。必须分别做单变量实验：仅改分块跑一次，仅改 Reranker 跑一次，最后做组合消融，才能得出可信结论。
- ⚠️ **避坑要点**：千万不要盲目追求总分提升而违背控制变量原则，无法归因的实验在工业界被称为垃圾实验。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 单变量实验需要消耗双倍的重跑算力与 API 费用
- 🛑 Trace 归因只能指出上下文缺失事实，无法修正大模型固有理解能力的盲区


---
