# R-P1-06: 如果要声称 DataPilot 支持 CSV、SQLite、MySQL，用哪些契约或验收场景证明三种源的 Schema、SQL 和隔离行为一致？

- **归属项目**：`DataPilot` | **题目类型**：`证据核验题` | **难度等级**：`进阶` | **核心主题**：`Agent, SQL, Sandbox`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 通过‘统一 Pydantic Schema 元数据契约、sqlglot 多方言 AST 静态审查、多源只读隔离机制与标准化端到端回归套件’四维对账，确保三类数据源行为强一致。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

要严谨声称同时支持 CSV、SQLite 与 MySQL，绝不能靠‘各写各的 if-else’，而是依赖四层统一契约与验收测试保障：第一，**统一元数据契约（Schema Contract）**：无论底层是文件还是关系库，`CsvAdapter`、`SqliteAdapter` 与 `MySqlAdapter` 均输出统一的 `SchemaSummaryRead` 与 `SchemaTableRead`，将物理字段类型归一化为标准的逻辑数据类型（INTEGER、FLOAT、STRING、DATETIME、BOOLEAN）；第二，**统一方言 AST 语法审查（SQLGuard）**：在 `packages/data_gateway/sql_guard.py` 中使用 `sqlglot` 分别解析 SQLite 与 MySQL 方言，执行相同的只读安全策略，严打注入与高危函数（如 `sleep`, `benchmark`, `load_file`），并强制注入 `LIMIT 1000`；第三，**统一只读隔离机制**：CSV/SQLite 实行容器只读挂载与内存沙箱加载，MySQL 采用专属只读账号与 `QueryCancelToken` 超时截断；第四，**统一验收回归套件**：通过 `tests/test_datasources_and_gateway.py` 与 `test_data_gateway_mysql.py` 执行同构查询验证。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

DataPilot 面向异构数据源（文件型 CSV、嵌入式 SQLite、网络型 MySQL）时，在契约设计、适配器实现与安全边界上的核心逻辑如下：

1. **统一数据源契约（Unified Contract）**：
- 在 `packages/contracts/datasources.py` 中定义严格的 Pydantic 模型：
  - `SchemaSummaryRead`：包含表名清单、主键标识、数据行数预估及脱敏字段标记；
  - `SchemaColumnRead`：字段名、数据类型（归一化为枚举）、是否可为空、注释说明；
  - `TableDataRead`：统一的行记录列名集合 `columns` 与数据行矩阵 `rows`，统一序列化为 JSON 兼容结构；
- 无论用户上传的是 CSV、挂载 SQLite 文件，还是配置远程 MySQL 连接串，上层 Agent 规划器看到的 Prompt Schema 结构完全同构，消除大模型由于数据源形态不同产生的理解漂移。

2. **适配器架构与 SQLGuard 方言级防御**：
- **适配器分层实现**：
  - `packages/data_gateway/adapters.py`：实现 `CsvAdapter`（基于本地只读解析）与 `SqliteAdapter`（利用 Python 原生 `sqlite3` 连接，以只读 URI `file:... ?mode=ro` 开启）；
  - `packages/data_gateway/mysql_adapter.py`：实现 `MySqlAdapter`（基于异步连接池，连接时配置只读会话）；
- **方言感知的 AST 审查（`sql_guard.py`）**：
  ```python
  # packages/data_gateway/sql_guard.py 核心逻辑
  _DANGEROUS_FUNCTION_NAMES = {
      "load_file", "sleep", "benchmark", "get_lock", "release_lock",
      "load_extension", "read_csv", "parquet_scan", "sqlite_scan"
  }

  def guard_sql(sql: str, dialect: Literal["sqlite", "mysql"]) -> SqlGuardResult:
      # 1. 利用 sqlglot 基于方言解析抽象语法树
      expression = sqlglot.parse_one(sql, read=dialect)
      
      # 2. 强制单语句且必须为只读 SELECT
      if not isinstance(expression, exp.Select):
          raise SqlGuardBlockedError("只允许执行只读 SELECT 查询！")
          
      # 3. 遍历 AST 禁止任何危险系统内置函数
      for func in expression.find_all(exp.Anonymous, exp.Func):
          if func.name.lower() in _DANGEROUS_FUNCTION_NAMES:
              raise SqlGuardBlockedError(f"检测到高危系统函数调用: {func.name}")
              
      # 4. 强制追加或收敛 LIMIT 至安全阈值（默认与上限 1000）
      _enforce_limit(expression, max_limit=1000)
      return SqlGuardResult(sanitized_sql=expression.sql(dialect=dialect))
  ```

3. **三种源的沙箱隔离与执行一致性**：
- **CSV 源**：由沙箱自动读入只读临时目录，通过 Python 脚本加载为不可篡改的 DataFrame 进行统计分析，或通过只读内存表支持 SQL 查询；
- **SQLite 源**：宿主机以只读权限通过 Docker volume bind 挂载进容器 `/workspace/data/source.db:ro`，沙箱内进程即使被提权也无法覆写源数据库；
- **MySQL 源**：数据库网关以只读账号（`GRANT SELECT ON ...`）建立连接，并注入全局查询超时，沙箱内部 Python 脚本不直接持有数据库直连凭证，而是由网关代理返回序列化结果。

4. **端到端验收与测试用例矩阵**：
在 `tests/test_datasources_and_gateway.py` 与 `test_data_gateway_mysql.py` 中沉淀了标准化验收矩阵：
- **测试场景 1（Schema 萃取对齐）**：同一种业务数据（如订单流水表）分别以三种存储形态存在，断言提取出的 `SchemaSummaryRead` 字段数、逻辑类型映射与空值标记完全一致；
- **测试场景 2（SQL 拦截等价性）**：测试用例注入 `DELETE FROM orders` 或 `SELECT SLEEP(10)`，验证在 SQLite 与 MySQL 方言下均被 `SqlGuardBlockedError` 拦截并抛出确定性异常码；
- **测试场景 3（大结果集截断一致性）**：无 LIMIT 的海量扫描查询，在三种源下均被强制分页并平稳截断于 1000 行，且在元数据中返回 `truncated: true`。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ **Pydantic 契约归一化**：`SchemaSummaryRead` 与 `TableDataRead` 抹平文件与关系库的结构差异；
- ✔️ **多方言 AST 防御**：`sqlglot` 分别解析 SQLite 与 MySQL 方言，统一拦截写操作、注入黑名单函数并限制 LIMIT 1000；
- ✔️ **多级只读隔离**：CSV/SQLite 文件物理 `:ro` 挂载，MySQL 细粒度只读账号 + `QueryCancelToken` 防御锁表；
- ✔️ **同构测试套件闭环**：`test_datasources_and_gateway.py` 覆盖 Schema 一致性、恶意 SQL 拦截及分页截断。

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问 1：MySQL 与 SQLite 的 SQL 语法有很大差异（如日期函数、字符串拼接和窗口函数），Agent 生成的 SQL 在跨源执行时出现方言不兼容怎么处理？

- 🎯 **考官意图**：考察对异构数据库方言差别的实际处理手段及 Agent Prompt 注入设计。
- 🛡️ **攻防标准应答**：我们采取了“**Prompt 方言前置注入 + 适配器层方言自适应降级**”的双重设计：1) **元数据前置注入**：Agent 在接收 Schema 时，Prompt 首行即显式声明当前连接方言类型（例如 `[Current DataSource: MySQL 8.0]` 或 `[Current DataSource: SQLite 3.x]`），并附带该方言的日期处理与截断建议（例如 MySQL 用 `DATE_FORMAT`，SQLite 用 `strftime`）；2) **网关语法回退机制**：如果模型生成的 SQL 在方言解析或执行阶段抛出语法错误，`sql_guard.py` 会捕获 `ParseError` 并构造结构化反馈（包含具体错误行列号与修复建议），触发 Agent 快速自纠错（Retry Loop），实测自纠错首轮成功率超过 85%。
- ⚠️ **避坑要点**：切勿回答“在中间写一个通用的 SQL 转换翻译器把所有语法转成通用 SQL”，对于复杂的复杂分析 SQL，方言转译器极其脆弱，给模型明确的方言上下文让模型原生生成是最优解。

###### 🎯 追问 2：CSV 格式如果遇到缺失列、类型推断错误或脏数据，如何避免让上层 Agent 产生幻觉？

- 🎯 **考官意图**：考察非结构化/半结构化数据源的鲁棒性校验与 Schema 嗅探能力。
- 🛡️ **攻防标准应答**：`CsvAdapter` 内部具备严格的 Schema 探测与质量审计流程：1) **编码与分隔符嗅探**：使用 `chardet` 探测编码，结合 `csv.Sniffer` 判定分隔符（逗号、制表符、分号）；2) **多采样强类型推断**：对前 1000 行样本进行强类型打分，只有全部满足整型/日期特征时才赋予强类型，否则优雅降级为 `STRING`，并记录 `sample_values` 与空值率；3) **向 Agent 暴露脏数据提示**：在生成的 `SchemaTableRead` 中，专门附带各列的 `null_percentage`（空值占比）和数据格式示例，提醒 Agent 在编写数据分析代码时显式使用 `.dropna()` 或 `COALESCE` 防御空指针。
- ⚠️ **避坑要点**：不要假定用户的 CSV 都是完美无瑕的，展示对真实业务脏数据防御的细致设计。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 **不支持跨异构源直接分布式联邦 JOIN**：不强行在系统内部实现自研分布式 SQL 引擎，多表关联由沙箱 Python 代码分别拉取后在本地合并；
- 🛑 **坚决禁用危险写入与存储过程**：无论数据源是哪一种，坚决禁止执行任何 DDL/DML 与存储过程调用。


---
