# T-F-10: 如何为一次面试回答建立“可验证 claim → 证据 → 代码/文档路径”的审计链？

- **归属项目**：`两个项目通用` | **题目类型**：`方法论与审计题` | **难度等级**：`进阶` | **核心主题**：`面试方法论, 审计链, 代码与事实闭环`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 坚持“无凭据不声称、无代码不虚构、无指标不溯源”原则：每一个业务 Claim 必须绑定可落盘的评测数据/日志证据，并精确对应到本地可复现的代码文件、类名与函数接口。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

在面对资深架构师或技术负责人的深度面试时，任何模糊的夸大、虚构的路径或空中楼阁的黑话都会瞬间击穿信任链。我为简历中的两项核心项目建立了**“三位一体”的确定性技术审计链（Claim ➔ Evidence ➔ Code/Doc Path）**：
1. **SuperMew（企业级 RAG 引擎）**：声称结构化分块提升证据覆盖率与通过率，审计链直接穿透到 `backend/indexing/document_loader.py` 的 `markdown_header_recursive_v1` 分块器、自动化对账脚本 `scripts/summarize_structured_chunking.py` 以及落盘的 JSON 实验产物；混合检索与重排直接对齐 Dense BGE-M3、Milvus BM25 与 Qwen3-Reranker-4B 的流水线；
2. **DataPilot（数据智能 Agent）**：声称只读 SQL 安全网关，审计链穿透到 `packages/data_gateway/sql_guard.py` 的 AST 解析拦截器、`_DANGEROUS_FUNCTION_NAMES` 黑名单与 `tests/test_datasources_and_gateway.py` 自动化测试；声称容器沙箱，精准对应 `apps/api/application/docker_sandbox.py` 的 8 重零信任隔离参数。

这套审计链确保我在任何深水区追问下，均可现场提供真实代码路径、接口定义与复现命令。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

为保证在面试中所有技术陈述坚不可摧，针对 SuperMew 和 DataPilot 梳理的完整审计链映射体系如下：

#### 一、 SuperMew 核心技术审计链
1. **Claim 1：采用结构化分块解决跨表断裂，证据完整覆盖率由 8.33% 提升至 54.17%，300 题大盘通过率由 62.00% 提升至 69.33%（净解决 22 题）**
- **证据文件与指标出处**：
  - 统计对账产物：`output/rag-evaluations/enterpriserag/enterpriserag-en-representative-structured-targeted-004/evaluations/structured-chunking-analysis-30-001/structured-chunking-impact-summary.json`
  - 核心指标：24 题定向集覆盖率净增 +45.83%，通过率净增 +29.17%（净解决 7 题：`qst_0023`, `qst_0142`, `qst_0189`, `qst_0312`, `qst_0331`, `qst_0335`, `qst_0423`）；300 题整体集通过率从 186/300 提升至 208/300。
- **真实代码与测试路径**：
  - 核心分块实现：`backend/indexing/document_loader.py`（类/方法：`markdown_header_recursive_v1` 结构化切分器，强制表格作为完整原子切块）
  - 自动化统计脚本：`scripts/summarize_structured_chunking.py`（单变量评测数据归集）
  - 自动化回归测试：`tests/test_structured_chunking_summary.py`

2. **Claim 2：密集 + 稀疏混合初筛（BGE-M3 + Milvus BM25）➔ RRF 倒数排名融合 ➔ 交叉重排（Qwen3-Reranker-4B）**
- **证据与流水线参数**：Dense 1024 维向量 Top 50，Milvus 原生 BM25 稀疏检索 Top 50，RRF ($k=60$) 融合截取 Top 30，Qwen3-Reranker-4B 交叉精排输出 Top 8 上下文。
- **真实代码路径**：
  - 流水线主入口：`backend/rag/pipeline.py`
  - 文档索引与向量化：`backend/indexing/document_loader.py`

---

#### 二、 DataPilot 核心技术审计链
1. **Claim 1：基于抽象语法树（AST）的只读 SQL 安全网关，拦截全量非只读、危险内建函数及注入越权**
- **证据与防护能力**：
  - 覆盖 SQLite 与 MySQL 双方言；
  - 严格拦截非 SELECT 语句（`INSERT`, `UPDATE`, `DROP`, `ALTER`, `GRANT` 等）；
  - 拦截危险高危函数黑名单（包含 `load_file`, `sleep`, `benchmark`, `load_extension`, `read_csv`）；
  - 强制注入并校验分页保护（默认 `LIMIT 100`，最大允许 `LIMIT 1000`）。
- **真实代码与测试路径**：
  - 核心拦截器实现：`packages/data_gateway/sql_guard.py`（核心类 `SqlGuard`，方法 `validate_sql`，常量 `_DANGEROUS_FUNCTION_NAMES`）
  - 核心测试套件：`tests/test_datasources_and_gateway.py`（包含多场景恶意 SQL 拦截用例）

2. **Claim 2：统一抽象适配异构多数据源（CSV、SQLite、MySQL）**
- **证据与契约规范**：实现统一的 `DataSourceAdapter` 协议，提供同构的 Schema 探查、字段类型映射与分页只读数据查询。
- **真实代码路径**：
  - CSV 与 SQLite 适配器：`packages/data_gateway/adapters.py`（`CsvAdapter`, `SqliteAdapter`）
  - MySQL 适配器：`packages/data_gateway/mysql_adapter.py`（`MySqlAdapter`）

3. **Claim 3：零信任 Docker 容器沙箱代码执行与资源强隔离**
- **证据与 8 重容器防御参数**：
  - 网络隔离：`--network none`（物理切断内外网）；
  - 资源上限：`--memory 512m`，`--cpus 1.0`；
  - 运行超时：CPU 超时 15s，物理超时 30s；
  - 磁盘安全：`--read-only`（根只读），挂载轻量只写内存盘 `--tmpfs /tmp:rw,noexec,nosuid,size=64m`；
  - 权限降级：`--user 10001:10001`（非 root），`--cap-drop ALL`（抛弃一切 Linux Capabilities）。
- **真实代码路径**：
  - 沙箱执行器：`apps/api/application/docker_sandbox.py`（类 `DockerSandbox`，方法 `run_python_code`）

4. **Claim 4：Agent 运行生命周期状态机与持久化事件流**
- **证据与一致性契约**：严格遵循 `QUEUED ➔ RUNNING ➔ SUCCEEDED / FAILED / CANCELED` 状态机；所有步骤事件携带单调递增 `seq` 序号，先写数据库持久化事务，再向前端 SSE 推送。
- **真实代码路径**：
  - 事件契约定义：`packages/contracts/run_events.py`
  - 编排调度与持久化：`apps/api/application/`

##### ⭐ 核心关键技术点 (架构图 / 流程树 / 数据流对齐)

```
                    [技术主张 Claim]
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
    [评测/日志/实验证据 Evidence]    [代码实现 Code Path]
             │                           │
  ├─ summary.json (净多答对22题)    ├─ document_loader.py (结构化分块)
  ├─ 8重沙箱隔离参数实录            ├─ sql_guard.py (AST只读校验+黑名单)
  └─ 200题盲测验证集隔离证明        └─ docker_sandbox.py (容器安全限制)
             │                           │
             └─────────────┬─────────────┘
                           ▼
              [闭环可验证的技术审计链]
```

面试应答审计链自查检查单（面试前自审模版）：
```python
AUDIT_CHECKLIST = [
    {
        "claim": "结构化切分使证据覆盖率从 8.33% 提升至 54.17%",
        "sample_size": "24 例单变量受控难题集（来自 43 份文档）",
        "evidence_file": "output/rag-evaluations/.../structured-chunking-impact-summary.json",
        "code_path": "backend/indexing/document_loader.py::markdown_header_recursive_v1",
        "reproduce_cmd": "python scripts/summarize_structured_chunking.py"
    },
    {
        "claim": "SQL 注入与高危函数防护，限制最大 1000 行查询",
        "sample_size": "覆盖 sqlite / mysql 双方言",
        "evidence_file": "tests/test_datasources_and_gateway.py",
        "code_path": "packages/data_gateway/sql_guard.py::guard_sql",
        "reproduce_cmd": "pytest tests/test_datasources_and_gateway.py"
    }
]
```

##### ❓ 面试官高频追问预判 (攻防反问 / 深水区探测)

###### 🎯 追问 1：如果面试官现场要求你打开 IDE 查看其中某个核心函数的具体实现，你会如何演示？
- 🎯 **考官意图**：考察代码是否为亲手编写，检验对工程细节的真实熟悉程度。
- 🛡️ **攻防标准应答**：
  我会立刻定位到核心文件并直切关键逻辑。例如面试官问 SQL 防护，我会打开 `packages/data_gateway/sql_guard.py`，展示 `validate_sql` 函数中如何使用 `sqlglot.parse_one` 解析 AST，指出我们如何遍历语法树节点，先检查根节点是否为 `exp.Select`，再检查 `find_all(exp.Anonymous, exp.Func)` 递归拦截 `_DANGEROUS_FUNCTION_NAMES`，最后演示如何检查并改写 `LIMIT` 子句。整套逻辑逻辑紧凑、行云流水，充分展现亲手实现的肌肉记忆。
- ⚠️ **避坑要点**：直接报出类名和关键方法，严禁支支吾吾翻找目录。

###### 🎯 追问 2：如果在面试中被问到某个指标由于测试环境变更有轻微浮动，如何通过审计链化解质疑？
- 🎯 **考官意图**：考察面对环境差异、网络波动时的工程把控力与解释弹性。
- 🛡️ **攻防标准应答**：
  我会主动出示实验的冻结快照和环境差异说明。在 SuperMew 中，我们记录了完整的输入快照、模型版本（Qwen2.5-72B-Instruct）和随机数种子。如果由于远端 API 升级或网络抖动产生波动，我能出示当初初筛 30 例中剔除的 6 例超时日志，说明我们是如何严格执行单变量清洗的。这不仅不会削弱真实度，反而更能证明我们在工程评测中对异常排查与实验受控的严苛态度。
- ⚠️ **避坑要点**：不强行辩解绝对精确到小数点后两位，而是展示清晰的实验版本与环境配置记录。

###### 🎯 追问 3：为什么很多候选人在讲项目时经常出现“文件路径对不上、参数张冠李戴”的情况？如何彻底杜绝？
- 🎯 **考官意图**：考察软件工程素养与知识沉淀体系。
- 🛡️ **攻防标准应答**：
  核心原因在于“口头表达与代码现实脱节”：许多候选人背诵的是通用架构八股文或博客教程，未与实际落地工程对齐。要彻底杜绝这一问题，必须在项目总结期建立“代码即真理（Single Source of Truth）”的映射文档，所有简历数字、架构图、配置参数必须由自动化脚本或单元测试背书，形成可一键跳转的代码行级索引。
- ⚠️ **避坑要点**：从工程规范高度总结经验，凸显资深开发者的敬业与严谨。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 绝不在面试中声称未在代码仓库中真实实现的虚构能力（如未落地的多模态向量索引）
- 🛑 绝不将开发期的临时原型代码与通过单元测试回归的生产代码混为一谈


---

### 模块十二：DataPilot 结论生成与脱敏呈现 (Final Answer & Redaction, T-G-01 ~ T-G-08)
