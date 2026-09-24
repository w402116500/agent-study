# AI Agent & RAG & LLM 面试通关全景知识库 (246 题)

> **SuperMew（企业级 RAG 检索增强） × DataPilot（受控数据分析 Agent） × 综合架构 × 98 道通用理论八股**  
> 全量覆盖 246 道核心技术面试题，提供**知识库文档站**与**沉浸式刷题自测平台**双端系统。

---

## ⚡ 核心系统与访问入口

本项目采用**双页面互通组合架构**，兼顾体系化全景研读与高强度面试自测：

| 平台名称 | 核心文件 | 定位与核心功能 | 访问与使用方式 |
| :--- | :--- | :--- | :--- |
| **知识库文档站** | [`index.html`](index.html) | **全景研读**：Docsify 零编译原生驱动，树形侧边栏、全局全文检索、代码一键复制、架构高清图缩放 | 部署 GitHub Pages 在线访问，或本地启动轻量静态服务秒开 |
| **专属全题库自测刷题平台** | [`study.html`](study.html) | **自测背诵**：246 题全景覆盖、**🎯 背诵遮罩自测模式**、掌握度实时打标追踪、快捷键顺滑切题、纯前端免 CORS 离线秒开 | **直接双击 `study.html` 本地即可直接使用** |

---

## 📚 题库全景模块概览 (246 题)

```text
大模型面试题/ (共 246 题 + 导读与合集)
├── 01_Agent面试题/            [24 题] Agent 核心概念、记忆体系、规划范式与 Multi-Agent 协作
├── 02_RAG面试题/              [21 题] 文档分块、向量数据库、Dense/BM25 混合检索、重排与评估
├── 03_LLM工具调用面试题/      [18 题] 原生 Function Calling、MCP (Model Context Protocol) 协议、A2A 架构
├── 04_大模型工程面试题/        [23 题] Prompt 优化、幻觉治理、微调对齐 (SFT/DPO)、推理加速与部署
├── 05_LangChain框架面试题/    [12 题] LCEL 表达式语言、LangGraph 状态机、Memory 与 Checkpointer
├── 06_SuperMew项目深挖/       [40 题] 真实企业 RAG：MinerU 解析、父子块补回、Milvus+ES、Qwen Rerank、Ragas 评测
├── 07_DataPilot项目深挖/      [66 题] 受控 Agent：guard_sql AST 防护、SQLite 状态机、Docker 隔离沙箱、SSE 先落库再推
└── 08_项目架构与综合追问/     [42 题] 全局架构权衡、大厂高频追问防御、Python 异步并发与 GC 底层原理
```

---

## 🎯 专属刷题平台 (`study.html`) 核心功能

1. **背诵遮罩模式 (Recitation Mode)**：按快捷键 `M` 或点击顶部按钮即可开启，自动隐藏详答部分，只露出口答应答思路与关键要点，按 `Space` 立即揭晓攻防标准答案。
2. **掌握度持久化打标**：
   - `1` 键：标记为**已掌握**（绿色）
   - `2` 键：标记为**模糊**（黄色）
   - `3` 键：标记为**待复习**（蓝色）
   - 顶部实时统计刷题率与掌握率，进度数据自动保存在本地 `localStorage`，刷新不丢失。
3. **极速键盘操作**：
   - `J` / `K` 或 `←` / `→`：无缝切换上一题 / 下一题
   - `R`：随机抽取一道题目进行模拟考核
   - `/`：快速聚焦搜索框进行模糊检索
4. **双端平滑跳转**：每道题右上角均配备 `📖 Docsify 原文 ↗` 按钮，一键在 Docsify 文档站中定位到对应 Markdown 章节。

---

## 🚀 本地运行与部署指南

### 1. 本地免环境秒开
- **刷题平台**：直接在文件管理器中**双击打开 `study.html`** 即可开始自测，无需安装 Node.js、Python 或任何数据库。
- **文档站**：可在本仓库根目录下启动轻量 HTTP 服务：
  ```bash
  # Python 3
  python -m http.server 8000
  # 浏览器访问 http://localhost:8000
  ```

### 2. GitHub Pages 云端在线托管
本仓库已包含 `.nojekyll`、`_navbar.md` 和 `_sidebar.md`，可零配置发布为个人线上知识库：
1. 打开 GitHub 仓库页面，进入 **Settings** -> **Pages**。
2. 在 **Build and deployment** 下的 **Branch** 选择 `main` 分支，路径选择 `/ (root)`，点击 **Save**。
3. 稍等片刻，即可通过 `https://<用户名>.github.io/<仓库名>/` 在线研读与自测刷题。

题解配图已压缩为 WebP（约 50MB，原先 PNG 超过 800MB）。GitHub Pages 上会优先走 jsDelivr 国内镜像加载图片，失败再回退到 Pages 源站。
