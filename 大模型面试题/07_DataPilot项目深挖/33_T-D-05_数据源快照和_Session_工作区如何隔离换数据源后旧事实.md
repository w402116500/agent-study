# T-D-05: 数据源快照和 Session 工作区如何隔离？换数据源后旧事实、旧 Artifact 和相对输入别名会怎样？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`Agent, 隔离机制, 状态管理`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> Run 快照复制物理文件，换数据源新旧 Run 按 datasource_id 隔离，旧事实不污染新源。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

DataPilot 在数据层面实施‘Run 输入快照’与‘Session 工作区’的双层隔离。每个 Run 启动时复制一份当前数据源的只读快照到独立的 `storage/inputs/{run_id}/`，杜绝并发覆写；用户在同一个 Session 内即使切换了数据源，新的 Run 也会强制分配新数据源的隔离目录，旧数据源的 Schema、SQL 结果、生成的 Artifact 与大模型记忆均被打上 `datasource_id` 标签，坚决禁止跨源带入，彻底防止数据污染。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

数据源快照与 Session 工作区隔离，及切换数据源时的状态失效机制：
1. **隔离边界架构**：
- **数据源快照（Datasource Snapshot）**：只读绑定于特定物理库与特定的 Schema Revision。不同数据源拥有完全独立的连接池、独立的表白名单、以及独立的元数据图谱。
- **Session 工作区（Session Workspace）**：每个分析 Run 拥有独立的本地工作目录（如 `/var/runs/{run_id}/`），包含临时的 `input/`、`output/` 和产物文件。

2. **切换数据源时的级联失效行为（Invalidation Cascade）**：
- **旧事实与结论标记归档**：前一个数据源查出的 SQL 数据与生成的推论被打上 `STALE_PREVIOUS_SOURCE` 标签，严禁作为新数据源推断的前提假设；
- **旧 Artifact 链接冻结**：前一个数据源生成的图表与 CSV 文件转为只读历史存档，新数据源的 Python 脚本绝不允许直接引用前一个数据源的相对路径产物；
- **输入别名重置**：清空任何指向旧库表结构的别名缓存，强制大模型重新进入新数据源的 Discovery 探查阶段。

3. **核心代码：数据源隔离与切换阻断器**：

```python
class SessionWorkspaceManager:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.active_datasource_id = None
        self.active_workspace_path = None

    def bind_datasource(self, new_datasource_id: str):
        """切换数据源触发全局上下文清理与安全断裂"""
        if self.active_datasource_id != new_datasource_id:
            # 1. 废弃旧的运行时工作区软链接
            self._archive_and_isolate_old_workspace()
            # 2. 建立新数据源的独立隔离沙箱目录
            self.active_datasource_id = new_datasource_id
            self.active_workspace_path = f"/var/sandboxes/{self.session_id}/{new_datasource_id}"
            # 3. 重置所有工具可访问的元数据上下文
            self._reload_isolated_schema_cache(new_datasource_id)
```

4. **防穿透原则**：严格禁止跨数据源（Cross-datasource）的隐式数据混合，保证企业多数据源环境下的审计合规边界绝对清晰。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ Run 启动原子克隆输入快照至独立路径，保障当前任务不受外界文件变更影响
- ✔️ 换数据源后通过 datasource_id 实行逻辑与元数据隔离，杜绝旧库事实跨源污染
- ✔️ 容器内相对输入别名在换源后原子重绑定，防止旧路径残留导致读错数据

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果用户的一个分析需求确实需要跨两个数据库进行 Join 分析，系统应该如何支持？

- 🎯 **考官意图**：考察多源联合分析架构与受控安全导出边界。
- 🛡️ **攻防标准应答**：绝不直接在底层数据库层面做跨库穿透连接。规范架构是：分别对两个数据源执行受控的只读聚合提取，将合规脱敏后的结构化中间数据集安全导入独立的数据沙箱中，在沙箱内部由 Python Pandas 进行内存级 Join 分析与融合计算。
- ⚠️ **避坑要点**：千万不要说配置数据库的 dblink 或跨库连接权限，这会彻底破坏多数据源的权限最小化原则。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 当前单次 Run 只支持绑定单一数据源，不支持在单次工具循环中动态 JOIN 两个异构数据源
- 🛑 会话历史跨源记忆遵循只读参考原则，数值结论必须基于当前活跃数据源重新验证


---
