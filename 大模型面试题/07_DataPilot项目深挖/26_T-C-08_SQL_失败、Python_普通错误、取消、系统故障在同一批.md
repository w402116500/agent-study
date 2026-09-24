# T-C-08: SQL 失败、Python 普通错误、取消、系统故障在同一批工具调用中分别如何决定继续还是停止整批？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`Agent, 异常处理, 容灾熔断`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 业务可修正错误允许回传 observation 继续，安全阻断、用户取消与系统故障立即熔断整批。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

在同一批串行工具调用中，系统根据异常严重度严格分流：业务型语法错误（如 SQL 报表名拼写错误、列不存在、LIMIT 缺失）作为安全的 observation 返回给模型，允许其在剩余配额内自我纠错；而安全越权阻断（如探测 DDL、跨库读取）、用户前端点击取消（Cancellation）、Docker 崩溃或网络宕机等基础设施故障，系统立即硬性熔断终止整批后续工具，终结当前 Run。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

批处理工具调用中四类错误的熔断与决策控制矩阵：
1. **四类故障本质划分**：
- **类 1：SQL 执行业务失败（如拼写错误、除以零错误）**：可修正软错误，允许模型看到错误栈并重试一次；
- **类 2：Python 普通运行时错误（如缺少依赖库、KeyError）**：沙箱内部异常，返回 Traceback 给模型自省；
- **类 3：用户主动取消（Client Cancelation）**：最高优先级中断，立即终止当前及后续一切操作；
- **类 4：基础设施故障（数据库死锁、Docker 守护进程宕机、OOM）**：硬故障，不可重试，立即熔断整批并系统报警。

2. **核心代码：分级错误调度判定器**：

```python
from enum import Enum

class FailureAction(Enum):
    CONTINUE_BATCH = "CONTINUE_BATCH"  # 独立错误，继续执行批次内其他非依赖调用
    RETRY_SELF = "RETRY_SELF"          # 允许大模型改写重试
    ABORT_ENTIRE_RUN = "ABORT_ENTIRE_RUN" # 立即硬中断整个会话

def determine_batch_action(error: Exception, failure_type: str) -> FailureAction:
    if failure_type == "USER_CANCEL":
        # 用户取消：立即停止整批，保护算力
        return FailureAction.ABORT_ENTIRE_RUN
        
    elif failure_type == "INFRA_OOM_OR_TIMEOUT":
        # 基础服务故障：不可恢复硬错误，熔断整批，落库 ERROR 终态
        return FailureAction.ABORT_ENTIRE_RUN
        
    elif failure_type == "SQL_SYNTAX_ERROR":
        # 模型写错 SQL：属于可解释错误，回传错误详情，由模型在下一轮尝试换个写法
        return FailureAction.RETRY_SELF
        
    elif failure_type == "PYTHON_RUNTIME_ERROR":
        # 脚本 KeyError 等：将 traceback 作为 ToolMessage 写回，模型可自愈
        return FailureAction.RETRY_SELF
        
    return FailureAction.ABORT_ENTIRE_RUN
```

3. **运行指标与安全红线**：
- 重试限额：可自愈错误（SQL/Python）单 Run 最多允许重试 2 次。超过 2 次无论什么原因立即降级熔断，严禁模型陷入死循环无休止消耗 API 费用。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 拼写、列不存在等语法错误返回安全提示，赋能大模型反思与自愈能力
- ✔️ DDL/DML 安全阻断、文件越权与探测立刻硬性阻断整批，绝不给攻击者暴力测试机会
- ✔️ 用户取消与底层物理沙箱崩溃直接熔断并触发统一收尾，保障系统计算资源不泄露

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果同一批次里第 1 个是 SQL 查询，第 2 个是独立的宏观行业指标查询（互不依赖），第 1 个失败第 2 个继续跑吗？

- 🎯 **考官意图**：考察多工具调用的依赖拓扑感知与独立分支容错机制。
- 🛡️ **攻防标准应答**：若两者在参数依赖图上不存在数据管道输入依赖（Decoupled Tasks），第 2 个独立工具照常执行；在最终汇聚阶段，大模型将获得‘部分成功’的数据集并向用户做出清晰交代，最大化保留用户的有效计算价值。
- ⚠️ **避坑要点**：不要一刀切全部杀死，也不要无脑无条件全部继续，必须基于参数依赖关系判断。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 重试次数硬卡为最多 2 次，超出后强行要求模型停止工具调用并输出已知信息
- 🛑 安全阻断记录直接记入高危安全告警日志，支持安全团队离线复盘


---
