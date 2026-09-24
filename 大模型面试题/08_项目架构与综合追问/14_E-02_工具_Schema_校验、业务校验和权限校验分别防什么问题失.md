# E-02: 工具 Schema 校验、业务校验和权限校验分别防什么问题？失败是否应该都让模型重试？

- **归属项目**：`两个项目通用` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`校验架构, 防御性设计, 错误处理, 重试策略`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> Schema 校验防格式错，业务校验防逻辑穿透，权限校验防越权滥用；仅参数与语法错误允许模型自愈重试。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

三重校验职责分明：Schema 校验防参数类型与缺参（Pydantic 拦截），业务校验防业务逻辑与实体不存在（如查询不存在的表名），权限校验防跨租户越权与危险注入（AST 白名单与 RBAC）。失败时绝不能无脑让模型重试：对于 Schema 格式错误和 SQL 语法错误，可将报错回传让模型自愈修正（限 1~2 次）；但对于权限越权（403）、安全白名单阻断或外部系统物理宕机，必须立即抛出终态错误并终止循环，否则会引发不可控的无意义 Token 消耗与死循环。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

在构建企业级 Agent 工具调用防线时，Schema 校验、业务校验和权限校验的职责划分与失败重试策略：
1. **三层校验的防御边界与场景参数**：
- **第一层：Schema 校验（语法与类型防线）**：
  - 拦截目标：参数类型错误（如期望 `limit: int` 但模型输出 `limit: "ten"`）、必填字段缺失。由 Pydantic 在进入业务代码前纳秒级拦截。
- **第二层：业务规则校验（领域逻辑防线）**：
  - 拦截目标：参数合法但违反业务规则（如财报分析中查询日期 `start_date: 2024-12-31` 晚于 `end_date: 2024-01-01`，或请求导出的表名不在白名单中）。
- **第三层：权限与安全校验（访问控制防线）**：
  - 拦截目标：横向越权（用户 A 查询机构 B 的保密财报）、非只读攻击（SQL 含有 `DROP` / `UPDATE`）。

2. **核心代码：三层递进拦截与自愈重试决策器**：

```python
from pydantic import BaseModel, Field, ValidationError
from typing import Optional, Dict, Any

class QueryParams(BaseModel):
    # Schema 校验：限制字段类型与取值范围
    ticker: str = Field(..., min_length=1, max_length=10, description="股票代码")
    limit: int = Field(default=10, ge=1, le=100, description="单次拉取行数")

def validate_and_execute_tool(user_ctx: Dict[str, Any], raw_args: Dict[str, Any]) -> Dict[str, Any]:
    # 1. 阶段一：Schema 格式校验
    try:
        validated_params = QueryParams.model_validate(raw_args)
    except ValidationError as err:
        # 允许重试：告诉模型具体的字段报错信息，引导其自行修复
        return {
            "retry_allowed": True,
            "error_type": "SCHEMA_ERROR",
            "message": f"参数格式校验失败: {err.errors()[0]['msg']}，请严格遵循 Schema 输出合法格式。"
        }

    # 2. 阶段二：权限边界校验
    if validated_params.ticker not in user_ctx.get("allowed_tickers", []):
        # 坚决禁止重试：越权行为绝不能让模型换马甲重试，直接阻断
        return {
            "retry_allowed": False,
            "error_type": "PERMISSION_DENIED",
            "message": "安全阻断：当前登录账户无权访问该标的的数据资产。"
        }

    # 3. 阶段三：业务规则校验
    if not is_market_open(validated_params.ticker):
        # 允许重试：告知业务事实，引导模型调用其他降级工具或向用户说明
        return {
            "retry_allowed": True,
            "error_type": "BUSINESS_LOGIC_ERROR",
            "message": f"标的 {validated_params.ticker} 当前处于非交易/停牌状态，请改查历史归档接口。"
        }
    
    return {"retry_allowed": False, "status": "SUCCESS", "data": execute_query(validated_params)}
```

3. **重试决策黄金法则与生产防坑**：
- **允许模型重试（Retryable）**：仅限 Schema 参数解析失败（格式畸变）、业务软性错误（如提示起止时间反了）。通过将标准化错误反馈给模型，让其在下一轮自行矫正；
- **坚决禁止重试（Non-retryable / Fast-Fail）**：权限越权拒绝、黑客注入攻击拦截、第三方接口持续 500 熔断。此类错误若让模型重试，只会引发无限循环消耗 Token，甚至诱导模型尝试越权绕过，必须立刻抛出硬终止并直出警示。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ Schema 校验抓格式类型，业务校验抓数据实体，权限/AST 校验守住安全底线与租户隔离
- ✔️ 可自愈的语法与轻微参数错误允许携带报错回传给模型重试，上限 2 次
- ✔️ 越权、安全注入与系统硬崩溃属于不可恢复错误，必须立即断路中断，严禁模型重试

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如何设计向模型回传的错误信息结构，既能引导模型有效修正参数，又不会向模型泄露内部敏感实现堆栈？

- 🎯 **考官意图**：考察安全脱敏与 Agent 反馈设计（Error Masking & Prompt Engineering）。
- 🛡️ **攻防标准应答**：采用【语义化错误抽象层（Sanitized Error Envelope）】：绝对剥离 Python Traceback、文件绝对路径、数据库物理表名和 SQL 原文；仅提取字段名、预期类型和业务约束。例如把 'psycopg2.OperationalError: table fin_secret_01 does not exist' 提炼为 '参数 table_name 不在允许查询的数据资产目录中，可选白名单为: [quarterly_sales, balance_sheet]'，既给了模型自愈路标，又杜绝了信息泄露。
- ⚠️ **避坑要点**：切忌把原始系统异常或堆栈全文直接打包进 tool response 回传给大模型。

###### 🎯 追问对决：如果模型连续两次因为 Pydantic 校验失败而死循环，如何通过兜底策略（Fallback）介入？

- 🎯 **考官意图**：考察多轮失败降级与重试熔断设计。
- 🛡️ **攻防标准应答**：设定【最大自愈重试窗口（Max Self-Healing Attempts = 2）】：在会话状态机中记录同一 tool 的连续错误计数。若第二次重试仍然 Schema 校验失败，不再回传给模型继续推理，而是触发系统级兜底策略（Fallback Interceptor）——直接向用户输出友好提示并请求人工介入澄清，或回退到只读的基础语义检索通道，同时记录报警日志。
- ⚠️ **避坑要点**：不要允许无限重试，必须设置硬计数器防止 Token 被恶意消耗殆尽。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 业务校验必须设计为无副作用的快速只读检查，不得在此环节执行重型外部网络请求
- 🛑 重试次数必须计入 Agent 的全局 Token 预算与最大轮数限制中


---
