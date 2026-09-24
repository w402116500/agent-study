# T-C-04: Discovery 只开放 `run_sql_readonly` 时，模型看到什么有限 observation，何时才能定稿分析计划？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`Agent, 状态机, Schema发现`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> Discovery 仅开放 run_sql_readonly 且只返回有限脱敏行和列结构，探清真实分布后才定稿 Plan。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

针对宽泛或复杂的业务问题，系统在正式分析前允许进入 Discovery（探测）阶段：此时只向大模型开放 `run_sql_readonly`，且模型只能看到受严格截断的有限脱敏行（最多 10 行）、字段名与数据类型，看不到完整原始全量数据。大模型利用这一有限 observation 验证数据是否为空、取值分布与枚举范围，确认可行后才正式调用 `start_data_analysis` 定稿完整分析计划。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

Discovery 阶段有限 Observation 暴露与计划定稿机制：
1. **业务场景与安全红线**：
- 场景：用户提问“分析 2024 年退货最多的 Top10 供应商”。
- Discovery 阶段职责：模型在编写主查询前，必须先探查数据库的元数据骨架（有哪些表、表之间通过什么外键连接、列名是 `return_rate` 还是 `refund_ratio`）。
- 有限 Observation 暴露规则：只允许调用 `run_sql_readonly` 查看元数据（如 `SHOW TABLES`、`\d+ orders`）或 `explore_datalink` 查看图谱拓扑；绝不允许在 Discovery 阶段拉取大宽表正文（行数被硬性锁死在 Top 5 样本行），且返回文本被裁剪在 500 字符内。

2. **核心代码：Discovery 有限观察与定稿门禁转移**：

```python
from typing import Dict, Any

def discovery_phase_guard(state: Dict[str, Any]) -> str:
    """
    决策状态机跳转路由：
    - 模型若继续申请探查工具：在预算内继续 DISCOVERY
    - 模型输出具备可执行逻辑的 Analysis Plan：跃迁到 EXECUTE
    - 超过 3 次探查依然无法定稿：强制收尾降级
    """
    plan = state.get("analysis_plan")
    discovery_rounds = state.get("discovery_rounds", 0)
    
    # 检查模型是否输出完整的定稿计划标记
    if state.get("plan_finalized", False):
        return "GOTO_EXECUTE"
        
    if discovery_rounds >= 3:
        # 防死循环红线：探查超过 3 轮必须强制定稿或报错
        return "GOTO_FORCE_FINALIZE"
        
    return "CONTINUE_DISCOVERY"
```

3. **何时定稿分析计划（Plan Finalization）**：
- 模型明确确认了“主表名”、“时间列格式”、“关键聚合度量列”三要素，并在回复中输出了显式 JSON/Markdown 结构体 `{"plan_status": "FINALIZED", "steps": ["1. 关联订单与退货表...", "2. 聚合前10并画图"]}` 后，状态机才正式解除执行锁，放开后续的计算与绘图权限。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ Discovery 阶段专用于宽泛问题的模糊探索，仅挂载 run_sql_readonly 工具
- ✔️ Observation 受到严格物理节流：最多 10 行采样、列敏感遮蔽、字符串截断，杜绝数据泄露
- ✔️ 模型摸清真实字段枚举与边界后，才提交结构化分析计划正式切入主执行流程

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果模型在 Discovery 阶段尝试执行 SELECT * FROM orders LIMIT 1000 偷跑全量数据，系统如何拦截？

- 🎯 **考官意图**：考察阶段级参数动态约束（Dynamic Phase Constraints）。
- 🛡️ **攻防标准应答**：在 Discovery 阶段，后端针对 `run_sql_readonly` 动态施加更苛刻的 AST 覆写拦截器，强制将最大允许行数从生产的 1000 行压低至 5 行，且自动剔除超长文本列，彻底粉碎模型在探查阶段偷跑大数据的行为。
- ⚠️ **避坑要点**：不要依赖模型的自我道德约束，必须在服务端协议层按 Phase 动态注入强制拦截策略。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 Discovery 阶段硬性限制最大探索轮数为 3 轮，超过限额强制要求定稿或退出
- 🛑 Discovery 阶段产生的临时表或子查询全部在事务回滚中销毁，不产生持久化 Artifact


---
