# T-F-04: 为什么 trace 必须记录实际执行路径，而不是只记录配置里“应该使用”的组件？

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`可观测性, Trace审计, 架构透明性`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 配置是预期目标，Trace 是物理现实；只有记录真实执行路径才能捕捉静默降级与故障。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

配置文件只反映静态预期（如预期使用 GPU Reranker 与自研知识图谱），但运行期存在网络超时、熔断降级、缓存击穿、本地兜底等大量动态分支。如果 Trace 只记录配置，一旦 Reranker 挂掉自动切入无序兜底，排查者会误以为是模型打分失效。Trace 必须真实记录实际经过的代码节点、耗时与入参出参，才能保证可观测性的绝对真实。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

Trace 必须记录实际物理执行路径而非配置“预期组件”的必要性：
1. **生产幽灵故障场景**：
- 场景：系统配置了 `reranker: "bge-reranker-large", cache: "redis_cluster"`。
- 隐蔽故障：线上高并发时，Redis 发生连接超时，代码隐蔽地进入了 `except: pass` 走降级内存缓存；Reranker 服务偶发超时 1.5s，代码自动降级为只取向量初筛结果。
- 致命误区：若 Trace 仅记录“配置计划（Config Intent）”，日志显示 Reranker 和 Redis 都在正常工作；评测人员排查 Bad Case 时便会误以为“bge-reranker-large 居然给这个黄金文档打了低分”，从而花费数周去错误地微调模型，完全掩盖了底层微服务超时的真实生产缺陷。

2. **核心代码：实际执行路径探针（Runtime Execution Telemetry）**：

```python
import time
from typing import Dict, Any

class ExecutionTraceRecorder:
    def __init__(self, trace_id: str):
        self.trace_id = trace_id
        self.actual_timeline = [] # 记录真实发生的事件物理链

    def log_actual_step(self, stage: str, component: str, is_fallback: bool, latency_ms: int, metadata: Dict[str, Any]):
        """只记录真实发生了什么的探针"""
        self.actual_timeline.append({
            "stage": stage,
            "actual_component_used": component,  # 例如 "FALLBACK_VECTOR_ONLY"
            "is_fallback": is_fallback,          # 明确标记是否触发了非预期降级
            "latency_ms": latency_ms,
            "timestamp": time.time(),
            "metadata": metadata
        })
```

3. **结论与审计价值**：
- 唯一的真理标准是**物理上到底哪行代码被执行了**。只有完整记录 `actual_component_used` 与 `is_fallback` 标记，才能在海量请求中秒级定位由于熔断降级引发的精度抖动。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 配置只代表静态初衷，Trace 必须忠实还原系统发生的动态分支与超时降级
- ✔️ 记录真实的实际执行组件，防止开发者因表面配置误判底层故障根本原因
- ✔️ 提供可复核的执行黑匣子，支撑生产事故定位与合规审计链条

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：这种高细粒度的 Trace 记录会不会在高并发下带来过高的磁盘 I/O 开销？

- 🎯 **考官意图**：考察分布式链路追踪的采样策略（Sampling Strategy）。
- 🛡️ **攻防标准应答**：采用【自适应分级采样机制】：正常 200 OK 且未触发降级的请求按 1% 采样落盘；一旦捕获到异常（Exception）、降级标志（is_fallback=True）、或 P99 慢请求（>2s），强制 100% 全量记录 Trace 现场，兼顾系统高吞吐与问题精准定位。
- ⚠️ **避坑要点**：不要说全量无差别写磁盘，也不要说什么都不记，必须基于错误和延迟做动态采样。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 Trace 记录物理路径，但不应把包含用户明文密码或未脱敏私密数据的 Payload 直接全量持久化
- 🛑 调试 Trace 采样率通常高于生产环境，生产环境需按百分比或错误级别动态调整


---
