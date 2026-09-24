# T-E-07: `answer.delta`、`answer.ready`、Assistant Message 和 `completion_kind=partial` 的生命周期如何区分？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`生命周期, 状态机, 流式输出`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> delta 驱动打字机，ready 固化终态与证据链，事实校验不一致时标记 partial 收尾。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

`answer.delta` 传输增量 Token 供前端打字机渲染；`answer.ready` 在大模型生成完毕后发出，携带完整正文 Markdown、`answer_evidence_refs` 与事实断言 `claim_summaries`；Assistant Message 此时写入会话历史供多轮交互；若事实校验未通过（如 `FINAL_ANSWER_FACT_MISMATCH`），系统不重新发散改数字，而是标记 `completion_kind=partial` 安全收尾。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

四大生命周期事件的分工与 completion_kind=partial 状态界限：
1. **四大事件的职责与边界**：
- `answer.delta`：大模型流式 Token 碎片，高频发射，用于实现打字机效果。属于临时瞬态流，不代表最终定稿。
- `answer.ready`：完整的终稿 Markdown 文本生成完毕，且已经通过了格式审查与敏感信息安检。通知前端可以关闭打字机光标，将内容固化为最终结论。
- `assistant.message`：会话历史存储模型中的不可变事实记录，包含完整的消息角色、时间戳、Token 消耗统计。
- `completion_kind = partial`：特殊终态标记，表示本次 Run 因超出预算、部分工具超时、或数据不全而提早安全收尾，产出了“有缺陷但有价值的部分结果”，而非彻底崩溃的 `FAILED`。

2. **核心代码：生命周期状态机收尾逻辑**：

```python
class RunCompletionManager:
    async def finalize_run(self, run_id: str, is_budget_exhausted: bool, full_content: str):
        if is_budget_exhausted:
            # 工具调用预算用尽：优雅降级为 partial 完成
            await self.db.update_run_status(
                run_id=run_id, 
                status="COMPLETED",
                completion_kind="partial",
                summary="因达到单次分析工具调用上限，已根据当前已核验数据生成阶段性结论。"
            )
            # 发射 ready 事件携带 partial 状态
            await self.sse.emit(run_id, "answer.ready", {
                "content": full_content,
                "completion_kind": "partial",
                "warnings": ["部分深层数据未完全展开"]
            })
        else:
            # 完美全量完成
            await self.db.update_run_status(run_id=run_id, status="COMPLETED", completion_kind="full")
            await self.sse.emit(run_id, "answer.ready", {"content": full_content, "completion_kind": "full"})
```

3. **用户体验与工程收益**：
- 明确区分 `partial` 与 `failed`，避免因边缘小异常导致整个耗时 20 秒生成的有效图表和核心数据全被当成“报错弹窗”丢弃，极大提升企业用户满意度。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ answer.delta 专供打字机低延迟流式呈现，不作为长期事实存储
- ✔️ answer.ready 携带正文与完成校验的证据引用，是前端展示可信依据的标准契约
- ✔️ 事实篡改或预算超限时果断标记 partial 终结，防止 Agent 无限重试与数字污染

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：前端在收到 completion_kind=partial 时，在交互上应该如何向用户呈现？

- 🎯 **考官意图**：考察人机协同（Human-in-the-Loop）在降级场景下的产品与交互设计。
- 🛡️ **攻防标准应答**：前端在答案卡片顶部渲染醒目的黄色警示条（Notice Banner），说明由于数据量过大或超时仅展示部分分析，并在底部提供交互按钮‘基于当前结论继续深度分析’，引导用户一键发起下一轮聚焦式的追问。
- ⚠️ **避坑要点**：不要弹大红色的 Error 报错 Toast，因为有价值的数据已经呈现，黄色提示才能正确引导用户。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 completion_kind=partial 依然属于终态，不会再次触发 Agent 自动修正循环
- 🛑 Assistant Message 中保存的是最终清洗后的 Markdown 文本，剥离了内部思考中间态


---
