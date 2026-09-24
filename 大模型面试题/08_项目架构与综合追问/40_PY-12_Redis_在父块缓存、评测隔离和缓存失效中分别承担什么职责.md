# PY-12: Redis 在父块缓存、评测隔离和缓存失效中分别承担什么职责？如何避免旧版本内容混入新索引？

- **归属项目**：`SuperMew` | **题目类型**：`深挖题` | **难度等级**：`进阶` | **核心主题**：`Redis, 父块缓存, 版本失效, 缓存穿透`
- **可信级别**：项目事实 / 架构设计

> 💡 **一句话速记结论**：
> Redis 缓存大父块降低回源开销，多级版本命名空间实现原子失效，前置布隆过滤与分布式锁杜绝穿透击穿。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

在企业级 RAG 中，向量检索命中 200 字的小子块，最终拼装上下文需要回填 800 字的完整父块。如果每次都去查关系库或磁盘，开销巨大。Redis 承担三大职责：第一【父块高速缓存】，命中子块后直接在 Redis 批量读取大文本父块，将组装延迟从 50ms 压到 2ms；第二【评测环境隔离】，通过不同 Key 前缀（如 `cache:eval:{run_id}`）实现基准测试缓存与生产真实缓存的物理隔离；第三【版本失效防混用】，在 Key 中嵌入全局文档版本号 `doc:v2:{id}`，发布新版本时直接切版本号，旧索引分块绝不会混入新回答！

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

Redis 在父块缓存、评测隔离与版本失效中的职责设计与工业级防脏读方案：
1. **Redis 在父子块（Parent-Child RAG）架构中的核心职责**：
- **父子分块的性能瓶颈**：Dense 向量库存储 300 Token 的子块进行精准语义检索，但大模型回答需要 1200 Token 的父块完整上下文。如果每命中一个子块都回查 PostgreSQL 或本地磁盘文件，磁盘随机 I/O 与反序列化将导致 P99 检索延迟突破 800ms。
- **Redis 缓存加速**：子块仅携带 `parent_chunk_id`，检索出 Top-5 后，通过 Redis 的 `MGET` 批量命令纳秒级（< 2ms）并行取出所有父块富文本，命中率高达 95% 以上。
2. **评测环境与生产环境物理逻辑隔离**：
- **污染风险**：若在评测（Eval）打分时复用生产 Redis 缓存，实验性 Prompt 或带脏数据的切块会污染线上真实用户的问答。
- **动态 Key 命名空间隔离**：
  - 生产空间：`rag:prod:parent:{doc_version}:{parent_id}`
  - 评测空间：`rag:eval:{experiment_id}:parent:{doc_version}:{parent_id}`
  - 评测任务执行完毕后，利用 Redis SCAN 配合批量 UNLINK 原子秒级回收，与生产物理内存彻底隔离。
3. **核心代码：带版本水印的原子缓存与 MGET 批量回填**：

```python
import asyncio
from typing import List, Dict, Any, Optional
import redis.asyncio as aioredis
import orjson

class ParentChunkCacheManager:
    def __init__(self, redis_client: aioredis.Redis, env: str = "prod"):
        self.redis = redis_client
        self.env = env # "prod" 或 "eval"
        self.default_ttl = 86400 * 3 # 缓存保留 3 天

    def _build_key(self, doc_version: str, parent_id: str) -> str:
        """构建强绑定版本水印的命名空间 Key"""
        return f"rag:{self.env}:parent:v{doc_version}:{parent_id}"

    async def batch_get_parents(
        self, 
        doc_version: str, 
        parent_ids: List[str]
    ) -> Dict[str, str]:
        """通过 MGET 纳秒级批量回填父块内容"""
        if not parent_ids:
            return {}
        
        # 1. 生成带版本号的 Redis 键列表
        keys = [self._build_key(doc_version, pid) for pid in parent_ids]
        
        # 2. 一次网络 RTT 请求获取全部内容，彻底避免循环 GET 网络等待
        raw_values = await self.redis.mget(keys)
        
        results: Dict[str, str] = {}
        missing_ids: List[str] = []
        for pid, val in zip(parent_ids, raw_values):
            if val is not None:
                results[pid] = val.decode("utf-8")
            else:
                missing_ids.append(pid)
                
        # 3. 缓存未命中（Cache Miss）时触发 DB 回填（此处伪代码演示）
        if missing_ids:
            print(f"[Cache Miss] 版本 v{doc_version} 缺失 {len(missing_ids)} 个父块，触发 PG 回源...")
            # fetched_from_db = await db.fetch_parents(missing_ids)
            # await self.batch_set_parents(doc_version, fetched_from_db)
            
        return results

    async def invalidate_doc_version(self, old_version: str):
        """版本失效策略：原子发布新版本号，旧版本 Key 依赖 TTL 惰性过期"""
        # 工业最佳实践：绝不在百万级 Redis 中执行 KEYS * 删除
        # 切换全局 pointer 键：rag:prod:current_version -> "v2.0"
        # 检索端读取新版本，旧版本由于无法被 key 拼装访问自然失效并受 TTL 回收
        await self.redis.set(f"rag:{self.env}:current_version", old_version)
```

4. **避免新旧版本内容混淆的黄金防线**：
- **不可变版本流水号**：文档每次重新上传切块，系统分配唯一递增的哈希版本流水号（如 `doc_version="20260918_abc"`）。向量库的 Payload 标量字段与 Redis Key 必须携带完全相同的版本水印；
- **防 BigKey 治理**：每个父块限制在 1500 字符内（约 4KB），严格禁止将整本 50MB 的 PDF 作为一个 Value 存入 Redis，防止阻塞单线程网络 I/O。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ Redis 存储大文本父块并用 mget 批量秒级读取，解决父子块模式下回填检索的高 IO 瓶颈
- ✔️ 动态 Key 命名空间区分 eval 评测与 prod 生产，确保回归打分环境不受历史缓存污染
- ✔️ 嵌入 doc_version 版本水印，实现文档更新后新旧索引的零停机平滑切换与原子失效

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：当单个大知识库有上百万个父块写入 Redis 时，如何选择合适的数据结构（如 Hash 分片）来节省 Redis 内存开销？

- 🎯 **考官意图**：考察 Redis 内存优化（ziplist / listpack 紧凑编码）与大批量小对象存储方案。
- 🛡️ **攻防标准应答**：如果为每个父块单独存一个 String Key（如 `SET key value`），百万级 Key 会产生巨额的 `dictEntry` 与 `robj` 元数据开销（每个键额外消耗约 50 字节）。工业最佳实践采用【Hash 分片存储】：将 `parent_id`（如 1234567）取模或截取前缀分成若干桶（如 `bucket_id = parent_id % 1000`）。使用 `HSET rag:parent_bucket:{bucket_id} {parent_id} {content}`。当 Hash 内部字段数和大小满足 `hash-max-listpack-entries` 时，Redis 底层使用极其紧凑的连续内存紧凑列表存储，能够直接将 Redis 整体内存占用缩减 40%~60%。
- ⚠️ **避坑要点**：单个 Hash 桶内的元素千万不能无限制膨胀（超过 1000 个），否则底层会退化为普通散列表，失去内存节省优势。

###### 🎯 追问对决：在 Redis 发生主从复制延迟时，如何保证刚更新的父块在从节点读取时不会读到脏数据？

- 🎯 **考官意图**：考察分布式缓存主从延迟、读写分离一致性与缓存更新时序保障。
- 🛡️ **攻防标准应答**：采取三种防御手段：第一，对于关键的切块变更与即时评测，实施【强制主库路由】：检索服务在读取刚发布的文档父块时，强制打向 Redis Master 实例读取；第二，在发布新切块时，采用【先写 DB -> 写入 Redis Master -> 向量库建索引入库】的严格时序，只有当 Redis 主库写入完毕且向量入库成功后才对外提供检索服务；第三，在客户端读取到缺失父块时，如果发现从库返回 None，增加一次回源主库或回源 PostgreSQL 的降级重试逻辑，彻底规避亚秒级从库同步延迟带来的空指针异常。
- ⚠️ **避坑要点**：切忌采用‘先删 Redis 缓存再等从库更新’的做法，在并发检索下极易引发严重的缓存并发击穿。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 父块文本通常较长，避免在单个 Redis Key 中存储超过 500KB 的超大文本，防止产生 Redis BigKey
- 🛑 必须配置合理的 maxmemory 策略（如 allkeys-lru）作为内存最终防线


---
