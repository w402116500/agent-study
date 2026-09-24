# T-D-03: 为什么 SQL 结果必须限制行数、字段和文本大小？模型为什么不应看到完整结果？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`基础` | **核心主题**：`Agent, 数据脱敏, 性能瓶颈`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 限制行数字段防止上下文爆炸击穿 Prompt 预算，大模型只需统计摘要无需阅读百万行全量。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

大模型的核心价值是基于数据分布进行统计推理与归纳，绝不需要把数万行原始明细全部通读。全量结果灌入会导致 LLM Context 瞬间被打满、计费账单剧增且推理延迟从秒级恶化至分钟级；此外还极易引发注意力迷失（Lost in the Middle）与数据泄露风险。系统强制限制最多返回 100 行（预览只给 10 行）、单字段文本截断并控制总 Payload 大小，全量计算交由 SQL 聚合完成。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

SQL 结果限制行数、字段与文本大小的三重防御机制：
1. **为什么模型绝对不应看到完整全量数据**：
- **Context 窗口爆炸（Context Saturation）**：哪怕只有 1 万行订单明细，转换成文本将消耗超 10 万 Token，直接击穿 LLM 的上下文窗口，且带来几十元不必要的 API 成本。
- **注意力涣散与大模型降智（Lost in the Needle）**：长文本灌入导致大模型无法专注在关键指标的推理上，幻觉率上升 3 倍以上。
- **数据泄露风险**：全量数据打印在 Prompt 中极易通过前端日志、中间网络抓包或 Prompt 注入攻击造成数据资产整体失窃。

2. **核心代码：三维数据剪裁与截断投影器**：

```python
from typing import List, Dict, Any

class DataTruncator:
    def __init__(self, max_rows: int = 100, max_cols: int = 20, max_cell_chars: int = 200):
        self.max_rows = max_rows          # 行数硬上限：模型最多只看 100 行观察样本
        self.max_cols = max_cols          # 列数上限：超过 20 列强制裁剪
        self.max_cell_chars = max_cell_chars # 单元格字符上限：防止长备注内容灌爆

    def truncate_for_llm_observation(self, raw_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_rows = len(raw_rows)
        # 1. 行截断
        truncated_rows = raw_rows[:self.max_rows]
        
        processed_data = []
        for row in truncated_rows:
            new_row = {}
            # 2. 列截断
            for col_idx, (k, v) in enumerate(row.items()):
                if col_idx >= self.max_cols:
                    break
                # 3. 单元格长度截断（针对长字符串）
                val_str = str(v)
                if len(val_str) > self.max_cell_chars:
                    val_str = val_str[:self.max_cell_chars] + "...[TRUNCATED]"
                new_row[k] = val_str
            processed_data.append(new_row)

        return {
            "columns": list(processed_data[0].keys()) if processed_data else [],
            "sample_rows": processed_data,
            "total_matched_rows": total_rows,
            "truncated": total_rows > self.max_rows
        }
```

3. **运行指标与生产原则**：
- 面向模型的观察只提供统计摘要与前排样本（Top 100 Rows）；
- 若业务需要处理数万行的全量计算（如计算整年均方差），模型必须生成聚合 SQL（`AVG`, `SUM`, `GROUP BY`）或生成 Python 脚本在沙箱内部流式计算，严禁把数据拉到 Prompt 层面做“人工大模型人肉计算”。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 大模型无法在内存中对万行明细精确求和，全量倾倒只会导致 Token 爆炸与注意力迷失
- ✔️ 强推计算下推原则：让数据库引擎做聚合计算，模型只阅读极简统计结果
- ✔️ 实施行数、列数、单元格长度三重截断，守住上下文安全与经济预算边界

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果模型确实需要用前 1000 行画趋势图，截断为 100 行后图表失真怎么办？

- 🎯 **考官意图**：考察数据流动通道的分层设计（模型观察层 vs 沙箱执行层）。
- 🛡️ **攻防标准应答**：采用【沙箱直读全量数据文件，模型仅看 Schema 摘要】的分离架构：SQL 查询出的 1000 行原始数据直接由后端落盘写入受控沙箱的 `/workspace/input/dataset.csv`；模型在 Prompt 里只看到字段名和前 3 行样例，随后模型生成 `pd.read_csv('input/dataset.csv')` 在 Python 沙箱中完成全部 1000 行的画图计算，兼顾了 Prompt 轻量化与图表精确度。
- ⚠️ **避坑要点**：不要为了画图妥协把 1000 行全文本直接塞进 Prompt，那是极度业余的做法。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 截断限制在网关层物理生效，大模型无法通过在 Prompt 中写‘请关闭 LIMIT’来突破限制
- 🛑 完整的全量数据仍可通过导出的 CSV 表格 Artifact 供用户在前端界面自行下载，不对模型端暴露


---
