# T-E-10: SuperMew 的来源引用与 DataPilot 的答案级证据有什么共同点和不同点？

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`系统对比, 证据溯源, RAG与Agent`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> SuperMew 绑定文档分块与相似度，DataPilot 绑定受控 SQL 审计与表格产物，皆防幻觉。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

共同点：两者都拒绝纯模型幻觉，强调“结论必有出处”，并在前端提供可交互的溯源凭证。不同点：SuperMew（RAG）绑定的是非结构化文档证据（`chunk_id`、文档名、原文片段、页码与检索分数）；而 DataPilot（受控 Agent）绑定的是结构化计算凭证（`audit_id`、只读 SQL 原文、数据库事务耗时、Table/Chart Artifact 引用及行列单元格）。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

前端事件乱序到达时的 seq 顺序还原与局部无闪烁刷新（DOM Reconciliation）：
1. **乱序成因与交互痛点**：
- 乱序成因：多路网络通道并发传输、或者重连补发流与实时流在特定边界交织到达。
- 交互灾难：若前端按收到顺序直接 Append DOM，会导致“分析结论跑到 SQL 工具前面”、“图表在闪烁两次后消失”，给用户带来极其劣质的破碎感。

2. **核心代码：前端事件重排序缓冲区（Jitter Buffer）与局部渲染**：

```javascript
class SSEOrderedStreamRenderer {
  constructor() {
    this.expectedSeq = 1;
    this.buffer = new Map(); // 缓存提前到达的失序事件
    this.state = { textDeltas: [], tools: {} };
  }

  onEventReceived(event) {
    const seq = parseInt(event.id, 10);

    // 1. 重复旧事件直接静默丢弃（防幂等）
    if (seq < this.expectedSeq) {
      return;
    }

    // 2. 存入乱序对齐缓冲区
    this.buffer.set(seq, event);

    // 3. 连续消费与状态机推演
    while (this.buffer.has(this.expectedSeq)) {
      const currentEvent = this.buffer.get(this.expectedSeq);
      this.buffer.delete(this.expectedSeq);
      this.applyEventToState(currentEvent);
      this.expectedSeq++;
    }

    // 4. 局部 DOM 无闪烁 Diff 刷新（虚拟化/局部挂载）
    this.renderIncrementalUI();
  }

  applyEventToState(ev) {
    if (ev.event === "answer.delta") {
      this.state.textDeltas.push(ev.data.delta);
    } else if (ev.event === "tool.start") {
      this.state.tools[ev.data.tool_id] = { status: "RUNNING" };
    }
  }
}
```

3. **运行指标与用户体验保障**：
- 缓冲区彻底屏蔽了 100~300ms 内的各种网络乱序；
- DOM 局部刷新采用数据驱动视图（虚拟 DOM / 局部 innerHTML 替换），杜绝整个页面发生全屏闪烁，保障丝滑流畅的打字机呈现。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 共同哲学：杜绝不可信生成，正文断言与事实凭据强制建立机器可读的映射关系
- ✔️ SuperMew 聚焦非结构化文本，以 Chunk ID、文档片段与检索相关度作为定性依据
- ✔️ DataPilot 聚焦结构化数值计算，以只读 SQL 审计号、不可变表格产物作为定量依据

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果其中一个 seq=3 的事件由于网络丢包永远没有到达，缓冲区的 expectedSeq 会永久卡死在 3 吗？

- 🎯 **考官意图**：考察前端乱序缓冲区的超时熔断与主动对账拉取机制。
- 🛡️ **攻防标准应答**：前端设置 500ms 乱序等待定时器（Hole Timer）：一旦发现 `seq=4` 到达而 `seq=3` 缺失，立即启动 500ms 倒计时；超时未到达则主动向服务端触发一次单点拉取 `/api/runs/{id}/events?seq=3`；若拉取确认不存在则直接跳过该序号，防止 UI 渲染永久假死。
- ⚠️ **避坑要点**：不要写死死等逻辑，任何缓冲队列都必须具备超时清道夫与自愈机制。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 RAG 证据侧重语义蕴含与召回充分性，允许少量的语言转述与格式重组
- 🛑 Agent 数值证据要求 100% 精确匹配，对统计数字零容忍任何程度的模糊变形


---


### 模块十一：DataPilot SSE 协议与事件回放 (SSE Streaming & Replay, T-F-01 ~ T-F-10)
