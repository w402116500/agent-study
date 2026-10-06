# DB-009: MySQL 与 PostgreSQL 的隔离、SQL 方言和优化行为有哪些区别？

- **归属模块**：`数据库与 SQL` | **优先级**：`P0` | **性质**：`通用原理` | **来源**：《Agent应用开发个人面经》（20261002 新版简历配套整理，本模块复制收录、内容未改写）

---

原题关联：新增：数据库基础与项目 SQL 能力展开

对应简历：CSV/SQLite/MySQL；PostgreSQL


#### 简要回答

两个数据库都支持关系查询和事务，但默认隔离、版本可见性、函数、日期语法、标识符和执行计划不同。MySQL 要说明 InnoDB 与版本，PostgreSQL 也要对应部署版本。DataPilot 多数据源生成 SQL 时必须显式区分 dialect，不能把通过一种数据库验证的 SQL 和安全规则直接套到另一种。


#### 详细解析


##### 1. 1. 事务名相同不代表完全同义

MySQL InnoDB 默认隔离通常是 Repeatable Read，PostgreSQL 默认 Read Committed；配置可以改变。InnoDB 普通一致性读和锁定读、范围锁，与 PostgreSQL 的快照和序列化失败语义不完全一致。回答先交代引擎与配置，再讨论业务读写，避免一句“RR 都没有幻读”覆盖所有情况。


##### 2. 2. SQL 与存储差异

日期截断、字符串函数、参数语法、大小写与标识符引用、JSON 与 upsert 形式都有差异。InnoDB 聚簇主键和 PostgreSQL 堆表也影响覆盖与回表解释。优化器选择依赖实际版本与统计，不能把某个索引规则绝对化推广。NULL、时区和数值精度则要按查询语义重点验证。


##### 3. 3. 项目角色不要混用

RAG 用 PostgreSQL 保存父块等关系信息，Redis 缓存，Milvus 检索；DataPilot 访问 SQLite、CSV 与 MySQL，元数据与业务取数也有不同角色。SQLGlot 解析和生成应知道目标 dialect，但解析成功不代表远程驱动支持全部语句。应以代表性跨源案例验证，并保留数据库专属安全限制。


#### 面试总结

- 明确引擎版本与配置
- 默认隔离与实际配置区分
- dialect 需要显式处理
- 项目各存储职责分别讲


#### 递进追问与参考答案


**追问 1：可以只换连接串就迁移数据库吗？**

通常不足。模型类型、迁移、方言函数、索引、隔离、事务和驱动都需核对；数据与约束也要迁移验证。ORM 缩小差异但不能消除全部数据库特性。


**追问 2：同一题两个数据库金额不同怎么查？**

先检查数据与时间范围，再查 NULL、时区、整数除法、DECIMAL/浮点、JOIN 粒度与排序限制。不要一开始就归因模型随机性；保留实际 SQL、参数和结果，才能定位语义差异。


#### 核查来源

- PostgreSQL 16 官方：事务隔离：`https://www.postgresql.org/docs/16/transaction-iso.html`
- MySQL8 事务隔离：`https://dev.mysql.com/doc/refman/8.0/en/innodb-transaction-isolation-levels.html`
- RAG PostgreSQL 默认配置：`E:/mystudy/agent_study/SuperMew/backend/infra/database.py`（第 6 行）

---


<a id="db-010"></a>
