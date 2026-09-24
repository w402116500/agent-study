# E-06: 如何为 Agent 设置最大轮数、预算和终止条件，避免“工具调用—错误—再调用”的死循环？

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`Agent终止, 死循环防御, Token预算, 状态机`
- **可信级别**：项目事实 / 核心控制

> 💡 **一句话速记结论**：
> 最大 5 轮硬终止、单会话 Token 预算硬熔断、连续重复调用指纹拦截，三重底线杜绝死循环。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

Agent 容易陷入'工具调用—报错—再调用—再报错'的无限死循环。破局的核心是'三层硬防线'：第一，最大轮数硬限制（Max Steps），生产环境严格限制单次分析任务不得超过 5 轮，达到 5 轮强制掐断；第二，Token 动态预算（Token Budget），单次会话设置 8k 输入/4k 输出硬阈值，超出立即熔断；第三，调用指纹哈希（Action Loop Detection），若检测到连续 2 轮发起相同工具且参数哈希一致却无法退出，立即阻断并由调度器接管，向用户返回'模型陷入重复推理，已安全终止'并给出已有阶段性分析结果。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

为 Agent 设置最大轮数、预算和终止条件，杜绝“工具调用—错误—再调用”死循环的防御架构：
1. **死循环发生机理与业务破坏力**：
- 诱因：模型生成了无效 SQL（如不存在的列名），系统回传错误；模型在下一轮仅微调了别名再次调用同一报错 SQL，循环往复直至撞上平台上下文上限。
- 破坏力：单次会话消耗数十万 Token（数元到数十元人民币），线程长时间被占满导致后端接口雪崩。

2. **核心代码：三层硬终止状态机与死循环熔断器**：

```python
import hashlib
from typing import List, Dict, Any

class AgentLoopGuard:
    def __init__(self, max_turns: int = 5, max_total_tokens: int = 8192):
        self.max_turns = max_turns                  # 1. 最大推理轮数硬上限
        self.max_total_tokens = max_total_tokens    # 2. 会话累计消耗 Token 预算
        self.consecutive_error_count = 0            # 3. 连续失败计数器
        self.recent_tool_hashes = []                # 4. 历史调用滑动指纹窗口

    def check_loop_condition(self, turn: int, total_tokens: int, tool_name: str, args: dict) -> None:
        # 判定一：轮数硬终止
        if turn >= self.max_turns:
            raise StopIteration(f"Agent 已达到最大安全迭代轮数 ({self.max_turns} 轮)，强制安全终止。")

        # 判定二：Token 预算熔断
        if total_tokens >= self.max_total_tokens:
            raise StopIteration(f"已达到当前会话 Token 预算消耗上限 ({self.max_total_tokens})，停止继续生成。")

        # 判定三：连续重复调用指纹（死循环行为检测）
        arg_sig = hashlib.md5(f"{tool_name}:{sorted(args.items())}".encode()).hexdigest()
        if self.recent_tool_hashes.count(arg_sig) >= 2:
            raise RuntimeError(f"检测到高频重复参数调用死循环: 工具 {tool_name}，系统拒绝重复执行并强制中断！")
        
        self.recent_tool_hashes.append(arg_sig)
        if len(self.recent_tool_hashes) > 6:
            self.recent_tool_hashes.pop(0)

    def record_step_result(self, is_error: bool):
        if is_error:
            self.consecutive_error_count += 1
            if self.consecutive_error_count >= 3:
                raise StopIteration("同一任务中工具连续报错超过 3 次，判定无法自愈，触发安全停机。")
        else:
            self.consecutive_error_count = 0
```

3. **优雅降级与用户引导**：
- **受控退出汇报**：触发终止时，系统绝不抛出白屏 500，而是捕获 `StopIteration`，将当前已收集到的中间事实、已尝试的步骤清单以及失败根因格式化展示给用户；
- **主动交还控制权**：提示用户“当前分析在第 4 步因字段歧义受阻，建议补充指定时间范围或检查指标定义”，让用户在下一轮对话中人工介入修正。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 调度层设置最大 5 轮硬截断，超过后剥夺工具调用权限并强制汇总
- ✔️ 会话级 Token 累计阈值与 60s 全局物理超时，双重熔断防算力失控
- ✔️ 滑动窗口记录工具参数哈希，连续 2 次相同调用即判定死循环并阻断

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果一个正常复杂的深度分析任务确实需要 7~8 步才能完成，系统如何安全地引导用户'授权继续'？

- 🎯 **考官意图**：考察人机协同（Human-in-the-Loop）与长周期任务的受控延续方案。
- 🛡️ **攻防标准应答**：采用【阶段性检查点（Checkpoint & Resume）机制】：当 Agent 步进达到第 5 轮预算门槛时，主动挂起当前 LangGraph 状态图，持久化所有中间数据，并通过前端下发一个带阶段小结的确认卡片：'已完成基础指标初筛与两张表的关联，预计还需 3 步生成预测图表，是否继续执行？'；用户点击确认后，携带当前 `checkpoint_id` 继续唤醒状态机，既保障了安全预算可控，又兼顾了深度任务的完整性。
- ⚠️ **避坑要点**：不要直接无脑把全局最大轮数从 5 改成 20，这会让所有死循环会话无节制烧钱。

###### 🎯 追问对决：在多步工具调用中，如何通过上下文动态剪枝（Pruning）来压缩前序轮次的冗余工具结果？

- 🎯 **考官意图**：考察长上下文窗口管理与 Token 优化策略。
- 🛡️ **攻防标准应答**：实施【中间结果摘要化与大块剥离（Tool Output Pruning）】：在第 N 轮推理前，扫描前序轮次的 `tool` 响应。如果第 2 轮查询返回的 100 行原始 JSON 已经在第 3 轮被模型提炼为了 3 行核心统计结论，则将第 2 轮的原始详细 JSON 替换为占位符 `[Data Summary: Q1 Sales Total=5.2M, row_count=100. Raw data pruned]`，仅保留关键结论，从而将上下文开销骤降 70% 以上。
- ⚠️ **避坑要点**：千万不能直接删除消息历史里的 `tool` 角色消息，否则会破坏模型的 tool_call 对齐协议导致 API 报错。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 硬终止可能会导致极其长尾复杂的任务未能给出最终完美图表
- 🛑 5 轮上限是平衡 95% 常见即席分析需求与安全兜底的工程折中


---
