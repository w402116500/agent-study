# T-D-06: Python 连接型 Run 的 `input/` 为什么可能为空？模型如果想画图，应如何先取得本 Run 已核验的数据？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`Agent, Docker沙箱, 数据流转`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 连接型源数据在远程库中，Python input/ 必然为空；画图必须先用 SQL 查出数据并传给脚本。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

当数据源是远程连接型（如远程 MySQL）时，数据存储在远端数据库服务器上，宿主机本地并没有文件实体，因此挂载进 Docker 沙箱的 `input/` 目录自然为空；系统绝不会在沙箱启动时愚蠢地把远程库全量拉取落盘。如果大模型后续想要用 Python 绘图或建模，规范路径是：先调用 `run_sql_readonly` 精准查询出聚合后的事实数据，再将该结果内联写入 Python 脚本的输入变量中运行。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

Python 连接型 Run 的 input/ 为空成因与已核验数据安全传递管道：
1. **input/ 为空的典型场景与设计哲学**：
- 场景推演：大模型在生成计划时，首轮直接调用 `run_python` 尝试画图，但此前从未调用过 `run_sql_readonly` 获取数据。
- 为什么 `input/` 此时为空：DataPilot 的沙箱工作区遵循“零信任与按需注入（Zero-Trust Injection）”。沙箱内部绝对不会预置任何数据库凭据，也不会自动挂载整个服务器目录。未在当前 Run 中被 SQL 审计核验过的数据，坚决不会出现在 `input/` 目录中。

2. **模型画图的正确执行链路（两阶段数据流）**：
- **阶段 1：数据查询与审计落盘**：模型必须先调用 `run_sql_readonly` 查询所需指标。系统通过 SQL 审计后，自动将脱敏后的结果集持久化为 `input/query_result.csv`。
- **阶段 2：沙箱消费与产物生成**：系统在随后的 `run_python` 调用中，将上述 CSV 文件安全只读挂载到沙箱容器内部的 `/workspace/input/`，模型编写 Python 脚本读取并绘图。

3. **核心代码：受控数据管道注入器**：

```python
import os
import pandas as pd
from typing import Dict, Any

class SandboxDataPipeline:
    def __init__(self, run_workspace_dir: str):
        self.input_dir = os.path.join(run_workspace_dir, "input")
        os.makedirs(self.input_dir, exist_ok=True)

    def inject_verified_sql_data(self, query_id: str, verified_rows: list) -> str:
        """将已通过审计的 SQL 结果安全写入 input/ 供 Python 消费"""
        target_csv_path = os.path.join(self.input_dir, f"{query_id}.csv")
        df = pd.DataFrame(verified_rows)
        # 写入物理 CSV，施加只读文件权限
        df.to_csv(target_csv_path, index=False, encoding="utf-8")
        os.chmod(target_csv_path, 0o444) # 444 只读权限，防止脚本篡改输入源
        return target_csv_path

    def validate_python_preconditions(self) -> bool:
        """检查 input 目录是否存在可用数据文件"""
        csv_files = [f for f in os.listdir(self.input_dir) if f.endswith(".csv")]
        return len(csv_files) > 0
```

4. **防坑提示**：若大模型在没有数据时直接执行画图脚本，执行器将立即拦截并报错：“Precondition Failed: 缺少输入数据，请先通过 run_sql_readonly 提取分析指标”，避免空脚本空转。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 远程数据库不落地全量文件，Docker 沙箱 input/ 初始为空，杜绝无意义的落盘倾倒
- ✔️ 模型必须先经由 SQL Guard 查出高度聚合的统计数据，再作为变量供给 Python 脚本
- ✔️ Python 容器完全断网且不持有数据库密码，从根本上阻断了沙箱内部反向拖库攻击

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：为什么把数据写成 CSV 文件挂载给 Python，而不是通过系统环境变量或标准输入 stdin 传递？

- 🎯 **考官意图**：考察大数据量进程通信与操作系统级资源限制的工程选型。
- 🛡️ **攻防标准应答**：环境变量受操作系统 ARG_MAX 大小限制（通常 2MB 内），且容易随子进程泄露到环境变量审计日志中；stdin 流式输入不利于 Pandas 快速进行随机访问与多索引切片。采用只读文件挂载可支持数万行数据秒级读取，且天然享受文件系统权限保护。
- ⚠️ **避坑要点**：不要回答通过环境变量传，数据量一大直接抛 Argument list too long 导致进程直接崩溃。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 Python 容器绝对不允许通过网络直连 MySQL 获取数据，必须由主程序作为受控网关中转
- 🛑 大模型在脚本中内联的数据必须与前序 SQL 返回的事实数据进行一致性校验


---
