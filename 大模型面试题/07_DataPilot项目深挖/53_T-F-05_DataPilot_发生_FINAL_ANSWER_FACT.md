# T-F-05: DataPilot 发生 `FINAL_ANSWER_FACT_MISMATCH` 时，为什么收尾为 partial 而不是重新接受模型改写的数字？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`事实校验, 幻觉防御, 降级收尾`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 发生事实不匹配时坚决不让模型重写，收尾 partial 避免幻觉震荡并保留真实表格证据。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

当触发 `FINAL_ANSWER_FACT_MISMATCH` 时，说明大模型在转述数据库真实结果时篡改了关键数字。此时系统坚决不让大模型重新解释或重写，因为让犯错的模型再次纠错极易诱发二次幻觉震荡、死循环并消耗巨额 Token。系统直接标记 `completion_kind=partial` 安全收尾，向用户明示正文数字存在偏差，并直接高亮真实的 Table Artifact 供人工核对。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

FINAL_ANSWER_FACT_MISMATCH 时收尾为 partial 而非重新接受模型改写数字的铁律：
1. **事故推演（为什么不能再给模型一次修改数字的机会）**：
- 场景：SQL 审计执行结果明确为：`{"sales_amount": 1250000}`。但大模型在最终总结中输出：“销售总额为 152 万元”（颠倒了数字）。
- 校验机制触发：后端数字对账引擎捕获到 `FINAL_ANSWER_FACT_MISMATCH` 事实不一致。
- 错误尝试（重新喂给模型重写）：若后端把错误发回给大模型：“你写错了，必须是 125 万”，大模型可能在下一轮不仅改了数字，还“自作聪明”地把推论解释篡改成“由于退货增加了 27 万导致最终调整为 125 万”——产生了更具欺骗性的**二次衍生幻觉**。

2. **核心代码：强制截断并固化 partial 降级输出**：

```python
def reconcile_final_answer(raw_markdown: str, verified_sql_metrics: dict) -> dict:
    """事实一致性硬对账引擎"""
    detected_mismatch = False
    for metric_name, true_val in verified_sql_metrics.items():
        # 检验大模型是否捏造或篡改了核心数值
        if not is_metric_truthfully_represented(raw_markdown, true_val):
            detected_mismatch = True
            break

    if detected_mismatch:
        # 坚决不接受模型重新狡辩，直接固化为 PARTIAL 终态
        return {
            "status": "COMPLETED",
            "completion_kind": "partial",
            "safe_markdown": raw_markdown,
            "fact_warning_banner": (
                "⚠️ 系统安全对账警示: 本结论中包含的部分数值可能与数据库实际审计结果存在偏差，"
                f"请以权威核验数据为准: {verified_sql_metrics}"
            )
        }
    return {"status": "COMPLETED", "completion_kind": "full", "safe_markdown": raw_markdown}
```

3. **商业分析安全底线**：
- **数据以审计表为唯一真理**。大模型只是文字包装器。一旦出现冲突，系统以加粗 Banner 方式明示物理查询数字，决不允许模型用幻觉掩盖幻觉。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 拒绝模型二次重写，防止诱发幻觉震荡、上下文污染与无底线 Token 消耗
- ✔️ 以 completion_kind=partial 安全收尾，透明披露事实不匹配审计告警
- ✔️ 强行置顶经审计的真实 Table Artifact，守住业务决策的准确性底线

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：这种数字对账是直接比对字符串吗？如果 SQL 返回 1250000，模型写成‘125万元’怎么匹配？

- 🎯 **考官意图**：考察数值归一化（Value Normalization）与单位换算对账技术。
- 🛡️ **攻防标准应答**：通过数值归一化引擎（Value Normalization Engine）：将大模型文本中的‘125万’、‘1250k’、‘1.25 million’等量词与阿拉伯数字，统一解析为标准浮点数 1,250,000.0，与 SQL 结果中的真实浮点值做允许误差范围（ε < 0.001）的数值等价性比对，避免因语法表达不同造成假阳性误拦截。
- ⚠️ **避坑要点**：不要说是单纯的字符串 substring 匹配，那是无法应对实际多变表达的幼稚做法。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 partial 收尾标志着本轮 Run 的物理终止，后续追问将在新的 Run 开启
- 🛑 该机制针对关键业务定量数字，对修辞性、总结性自然语言不做过度严厉阻断


---
