import sys, os, urllib.parse, re
sys.stdout.reconfigure(encoding='utf-8')

from parse_test import MODULES_DEF, BASE_MD_DIR, ROOT_DIR

def build_docsify_files():
    # 1. .nojekyll
    nojekyll_path = os.path.join(ROOT_DIR, '.nojekyll')
    with open(nojekyll_path, 'w', encoding='utf-8') as f:
        f.write('')
    print("Created .nojekyll")

    # 2. _navbar.md
    navbar_lines = [
        "* 📚 通用基础篇",
        "  * [01 Agent 核心概念与规划](大模型面试题/01_Agent面试题/00_Agent%20面试题介绍.md)",
        "  * [02 RAG 检索增强架构](大模型面试题/02_RAG面试题/00_RAG%20面试题介绍.md)",
        "  * [03 工具调用与 MCP 协议](大模型面试题/03_LLM工具调用面试题/00_LLM工具调用面试题介绍.md)",
        "  * [04 大模型工程与落地](大模型面试题/04_大模型工程面试题/00_大模型工程面试题介绍.md)",
        "  * [05 LangChain 框架实战](大模型面试题/05_LangChain框架面试题/00_LangChain%20框架面试题介绍.md)",
        "* 🐱 [SuperMew 项目 (40题)](大模型面试题/06_SuperMew项目深挖/00_SuperMew项目深挖介绍.md)",
        "* 📊 [DataPilot 项目 (66题)](大模型面试题/07_DataPilot项目深挖/00_DataPilot项目深挖介绍.md)",
        "* 🏗️ [架构与综合追问 (42题)](大模型面试题/08_项目架构与综合追问/00_项目架构与综合追问介绍.md)",
        "* 📖 [全景大纲](大模型面试题/README.md)",
        "* ⚡ [**刷题自测平台 (study.html)**](study.html ':target=_self')"
    ]
    navbar_path = os.path.join(ROOT_DIR, '_navbar.md')
    with open(navbar_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(navbar_lines) + '\n')
    print("Created _navbar.md")

    # 3. _sidebar.md
    sidebar_lines = [
        "* [🏠 **题库总纲与全景导读**](大模型面试题/README.md)",
        "* [⚡ **专属刷题自测平台**](study.html ':target=_self')",
        ""
    ]

    for mod in MODULES_DEF:
        m_dir = mod["dir"]
        m_path = os.path.join(BASE_MD_DIR, m_dir)
        sidebar_lines.append(f"* **{mod['name']}**")
        
        # Check for 00_ introduction
        intro_files = [f for f in os.listdir(m_path) if f.startswith('00_')]
        if intro_files:
            enc_intro = urllib.parse.quote(intro_files[0])
            sidebar_lines.append(f"  * [📖 模块导读与考点综述](大模型面试题/{m_dir}/{enc_intro})")
        
        # Check for full collection
        col_files = [f for f in os.listdir(m_path) if '_完整合集.md' in f]
        if col_files:
            enc_col = urllib.parse.quote(col_files[0])
            sidebar_lines.append(f"  * [📚 本模块完整题解合集](大模型面试题/{m_dir}/{enc_col})")
        
        # Questions
        q_files = sorted([f for f in os.listdir(m_path) if f.endswith('.md') and not (f.startswith('00_') or f.endswith('_完整合集.md') or f in ['README.md', '目录.md'])])
        for qf in q_files:
            # Clean label for sidebar
            lbl = qf.replace('.md', '')
            # If 01_1. xxx -> 01 xxx
            lbl = re.sub(r'^\d+_', '', lbl)
            lbl = re.sub(r'^\d+\.\s*', '', lbl)
            # Truncate if too long
            if len(lbl) > 28:
                lbl = lbl[:28] + '...'
            enc_qf = urllib.parse.quote(qf)
            sidebar_lines.append(f"  * [{lbl}](大模型面试题/{m_dir}/{enc_qf})")
        
        sidebar_lines.append("")

    sidebar_path = os.path.join(ROOT_DIR, '_sidebar.md')
    with open(sidebar_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sidebar_lines) + '\n')
    print("Created _sidebar.md")

build_docsify_files()
