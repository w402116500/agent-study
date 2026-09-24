# R-P3-09: 提到 Docker Sandbox；模型能看到哪些路径，脚本能写哪些路径，如何防止符号链接或联网？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`Sandbox, 系统设计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 模型只能看到只读挂载的 input/ 相对路径；脚本仅允许写 output/；内核级断网并以真实解析路径阻断软链逃逸。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

在 Docker 沙箱隔离设计中，模型绝对看不到宿主机物理路径：它看到的只是容器内的标准化相对路径 `/workspace/input/`（以 `ro` 只读方式挂载，存放本 Run 固化的数据快照）；脚本唯一具备写权限的只有 `/workspace/output/`；容器启动参数强制指定 `--network none`（物理断网），并且我们禁用了所有特权能力；当容器执行完毕向宿主机拷贝产物时，宿主机代码通过 `os.path.realpath` 强制校验解析路径，只要发现是指向根目录的符号链接立即销毁抛错。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

Docker Sandbox 的路径可见性、隔离与内核防逃逸：
1. **模型与脚本的文件系统权限边界**：
- **只读输入挂载**：主机数据目录以 `:ro`（Read-Only）挂载到容器内 `/workspace/input/`，模型只允许通过只读句柄读取 CSV/Parquet 快照；
- **隔离写出目录**：容器内仅 `/workspace/output/` 具有可写权限，用于保存生成的图表 PNG 和分析结果 JSON；
- **网络与系统隔离**：`--network none` 彻底关闭网络栈；内存硬上限 512MB（`--memory 512m`）；超时 15s 硬杀死。

2. **核心代码：Docker 安全执行命令与沙箱控制器（含逐行注释）**：
```python
import asyncio
import os
import subprocess

async def run_in_docker_sandbox(script_path: str, input_dir: str, output_dir: str, timeout: int = 15) -> dict:
    """在无网络受限容器中执行分析脚本"""
    # 构造 Docker 安全运行参数
    cmd = [
        "docker", "run", "--rm",
        "--network", "none",                  # 物理断网，严禁向外渗漏数据
        "--memory", "512m",                   # 限制最大内存 512MB，防止内存炸弹
        "--cpus", "1.0",                      # 限制最多单核算力
        "--pids-limit", "64",                 # 限制最大进程数，防止 fork 炸弹
        "-v", f"{os.path.abspath(input_dir)}:/workspace/input:ro",   # 输入目录只读
        "-v", f"{os.path.abspath(output_dir)}:/workspace/output:rw", # 输出目录可写
        "datapilot-python-sandbox:latest",
        "python", f"/workspace/input/{os.path.basename(script_path)}"
    ]

    # 启动子进程执行并施加严格超时
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "success": proc.returncode == 0,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "returncode": proc.returncode
        }
    except asyncio.TimeoutError:
        proc.kill()  # 容器超时强制杀掉
        return {"success": False, "error": "Sandbox Execution Timed Out (15s limit)"}
```

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 容器只读挂载 input/，仅允许向 output/ 写入，杜绝宿主机绝对路径泄露
- ✔️ 底层强制 network_mode='none' 物理断网，彻底防御数据外泄与反弹 Shell
- ✔️ 宿主机产物提取强制 realpath 校验，有效防御符号链接逃逸攻击

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果 Python 脚本调用了大量递归导致栈溢出，沙箱的 cgroups 限制是多少？

- 🎯 **考官意图**：考察 Linux 容器底层资源配额与硬件护栏参数。
- 🛡️ **攻防标准应答**：内存硬上限通过 Docker `--memory 512m` 限制为 512MB，栈溢出导致内存激增时会直接触发 OOM-Killer 终结容器；同时配置 `--pids-limit 64` 限制并发进程树，外加 Python 解释器默认的 `sys.setrecursionlimit(1000)` 保护，从应用层和操作系统双重兜底。
- ⚠️ **避坑要点**：不能只说'有超时'，递归和死循环必须有内存、线程数与解释器递归深度的硬参数防护。

###### 🎯 追问对决：在没有网络的情况下，Python 脚本如何引入依赖库（如 pandas, seaborn）？

- 🎯 **考官意图**：考察离线镜像打包与生产依赖固化策略。
- 🛡️ **攻防标准应答**：所有必须的科学计算与可视化库（pandas, numpy, matplotlib, seaborn, openpyxl）均在 Docker 镜像构建时（Dockerfile）预先安装固化在基础镜像内，脚本运行时完全依托本地 site-packages，绝不在运行期动态 pip install。
- ⚠️ **避坑要点**：切勿说'运行时用代理访问内网 PyPI'，断网沙箱的核心原则就是容器内严禁任何出站连接。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 镜像在构建阶段必须提前预装所有科学计算与绘图依赖，运行期无法 pip 安装
- 🛑 Docker 隔离基于 Linux Namespace，需确保宿主机 Docker 守护进程未开启特权模式


---
