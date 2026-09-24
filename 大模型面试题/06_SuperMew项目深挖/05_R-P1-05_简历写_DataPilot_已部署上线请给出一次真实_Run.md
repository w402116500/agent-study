# R-P1-05: 简历写 DataPilot 已部署上线；请给出一次真实 Run 的成功标准、错误率/延迟观测和仍未具备的生产能力。

- **归属项目**：`DataPilot` | **题目类型**：`证据核验题` | **难度等级**：`进阶` | **核心主题**：`Agent, 系统设计, 评测`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 一次真实 Run 的成功标志是‘状态机闭环至 SUCCEEDED、全生命周期单调递增 seq 事件落盘入库、通过 SQLGuard/Docker 三道防线、生成注册哈希的 Artifact’；当前支持容器化可观测运行，但尚未具备多租户行级隔离与长驻交互式内核。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

在 DataPilot 中，一次真实 Run 的成功标准包含四层硬性验收：第一，**状态机严格流转至终止态**：`QUEUED -> RUNNING -> SUCCEEDED`，无未捕获异常或超时；第二，**事件流先落盘后推送**：全生命周期的 20+ 类 `RunEventType` 事件（从 `run.queued` 到 `answer.ready`）按严格单调自增 `seq` 序号写入数据库，并在前端断线后支持完整回放；第三，**安全三道闸门全部放行**：通过 AST 级只读检查（SQLGuard）、Docker 沙箱安全隔离执行（`--network none`, 512MB RAM, 30s 墙钟超时）并通过 `FinalMarkdownPayload` 契约校验；第四，**产物可追溯**：输出的表格或图表生成全局唯一 ID 与 SHA-256 并注册进 `ArtifactStore`。延迟与错误率通过 Prometheus 指标与落盘事件精准追踪。坦诚而言，当前版本定位于企业内网受控数据分析系统，尚未具备多租户行级 RLS 与超大分布式数据集的即席计算能力。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

DataPilot 作为一款严肃的端到端数据分析 Agent，其底层执行引擎与可观测性设计具备严格的工程边界：

1. **一次真实 Run 的四维成功验收标准**：
- **状态流转与生命周期闭环**：
  遵循 `packages/contracts/status.py` 定义的 `RunStatus`，从 `QUEUED` 启动，经 `RUNNING`，最终原子性更新为 `SUCCEEDED`（若失败则确切置为 `FAILED` 或 `CANCELED`），严禁状态悬空或僵尸任务；
- **全链路顺序事件持久化（Durable Sequential Events）**：
  核心事件定义于 `packages/contracts/run_events.py` 的 `RunEventType`：
  `run.queued` ➔ `run.started` ➔ `run.protocol.selected` ➔ `tool.called` ➔ `tool.succeeded` ➔ `artifact.created` ➔ `answer.ready` ➔ `run.succeeded`。
  所有事件**必须先持久化写入数据库并分配全局单调自增 `seq` 整数序号**，再通过 Server-Sent Events（SSE）广播给前端，保证客户端网络重连时只需携带 `last_seq` 即可零丢失补齐全量状态；
- **三道安全与结构闸门**：
  - *第一闸（SQLGuard 静态校验）*：`packages/data_gateway/sql_guard.py` 利用 `sqlglot` 构建 AST，校验 SELECT 语句，拦截数据修改与高危函数（如 `load_file`, `sleep`, `benchmark`, `load_extension`），强制注入 `LIMIT 1000`；
  - *第二闸（Docker 沙箱执行隔离）*：`apps/api/application/docker_sandbox.py` 执行 Python 生成脚本，应用最严安全配置：`--network none`、`--memory 512m`、`--cpus 1`、`--user 10001:10001`、`--cap-drop ALL`、`--read-only`；
  - *第三闸（输出契约核验）*：结构化数据必须通过 `FinalMarkdownPayload` 与 `ArtifactModel` 序列化校验；
- **产物资产化注册**：
  沙箱中生成的图表与脱敏中间表写入只读挂载目录，由 `ArtifactStore` 计算 SHA-256，生成可被引用的角标引用锚点。

2. **错误率与端到端延迟的可观测性（Observability）**：
- **Prometheus 监控指标**：
  - `datapilot_run_total{status="succeeded|failed|canceled"}`：按终态维度的调用计数；
  - `datapilot_run_duration_seconds`：Histogram 统计端到端耗时；
  - `datapilot_sandbox_execution_seconds`：沙箱容器从拉起、执行到回收的毫秒级耗时；
- **阶段耗时基线分解**：
  一次典型的数据分析 Run 整体耗时约为 8~18 秒：
  1. 元数据与 Schema 获取阶段：~200ms；
  2. Agent 意图识别与 SQL 生成/执行阶段：~1.5s~3s；
  3. 沙箱容器启动与代码执行阶段：~2s~5s（受限于 Docker 容器创建与 Python 解释器冷启动）；
  4. 结论整理与最终渲染呈现阶段：~3s~6s。

3. **诚实呈现：系统当前仍未具备的生产能力（Honest Boundaries）**：
- **缺乏多租户行级安全（Row-Level Security, RLS）**：目前通过数据库专属只读账号隔离，未集成面向多租户动态拼接 SQL 的细粒度行级/列级动态遮蔽策略；
- **单机 Docker 架构而非 Kubernetes 分布式调度**：沙箱由宿主机 Docker Daemon 实例化，单节点并发受限于宿主容器资源，未实现跨节点 K8s Pod 弹性漂移；
- **无长驻交互式会话内核（Stateful Kernel）**：每个分析轮次执行完毕后沙箱立即销毁，不支持类似 Jupyter Notebook 在内存中持久驻留百兆 DataFrame 进行连续追加交互。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ **四层成功验收**：状态机终态闭环、单调自增 seq 事件落盘、三道防线放行、SHA-256 产物注册；
- ✔️ **事件先落盘后推送**：20+ 类 `RunEventType` 入库后分发 SSE，支持前端重连零丢失对账；
- ✔️ **纵深防御隔离**：SQLGuard 语法 AST 审查 + Docker 沙箱极致受限环境（无网络/只读/无特权）；
- ✔️ **坦诚生产边界**：清楚指出缺少多租户动态 RLS、缺乏 K8s 分布式调度及无持久内存内核。

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问 1：如果前端在接收 SSE 流中途断网了，重新连接后你们怎么保证界面不会卡在中间状态或丢事件？

- 🎯 **考官意图**：考察分布式前端通讯可靠性设计与断点续传（Event Stream Resiliency）。
- 🛡️ **攻防标准应答**：我们通过“**自增 Sequence 序号 + 服务端持久化回溯**”从根本上解决：1) 服务端每生成一个事件（如 `tool.called`, `artifact.created`），先写入数据库事务，生成严格单调自增的主键 `seq`（如 seq=1, 2, 3...）；2) 前端重连发起 SSE 请求时，在 Header 或 Query 中携带 `last_event_seq`；3) 服务端检索 `WHERE run_id = :id AND seq > :last_event_seq ORDER BY seq ASC`，瞬间全量补发断网期间积压的所有事件，随后无缝切回实时流推送；4) 前端根据终态事件（`run.succeeded` 或 `run.failed`）决定是否关闭连接。这一机制保证即便用户刷新页面或手机熄屏重开，界面也能在毫秒内还原到一致状态。
- ⚠️ **避坑要点**：千万不要回答“前端轮询接口重新拉一次结果”，要强调基于单调 `seq` 的优雅增量追平。

###### 🎯 追问 2：既然每个 Run 都会启动一个全新的 Docker 容器，高并发下频繁创建和销毁容器会不会把系统压垮？

- 🎯 **考官意图**：考察候选人对容器沙箱性能瓶颈的清醒认识与架构预案。
- 🛡️ **攻防标准应答**：我们对这一瓶颈有着非常清晰的技术权衡：在当前的企业内网分析场景下，我们优先选择**绝对的安全性与资源隔离**，避免用户恶意代码或死循环污染主机内存，因此每个 Run 分配全新独立容器（耗时在 800ms~1.5s 左右）。为防范资源耗尽，我们设置了并发信号量（Max Concurrent Workers）与排队机制（QUEUED 状态缓冲）。如果后续需要面向互联网海量 C 端高并发，演进路径将是**预热容器池（Pre-warmed Container Pool）**与轻量级虚拟化技术（如 Firecracker MicroVM / gVisor），在几毫秒内完成快照恢复，兼顾极致隔离与吞吐。
- ⚠️ **避坑要点**：不要声称现在的单机 Docker 架构能抗住每秒几万 QPS，坦诚承认并发瓶颈并给出成熟的工程演进路线。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 **不追求亚秒级即席响应**：优先保障容器安全隔离与审计合规，接受秒级冷启动耗时；
- 🛑 **放弃沙箱内网络依赖**：代码运行禁止任何出站网络（`--network none`），所需数据通过挂载提供。


---
