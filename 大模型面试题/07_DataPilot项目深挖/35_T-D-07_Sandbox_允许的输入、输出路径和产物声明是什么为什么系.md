# T-D-07: Sandbox 允许的输入、输出路径和产物声明是什么？为什么系统不扫描目录寻找“安全结果”？

- **归属项目**：`DataPilot` | **题目类型**：`深挖题` | **难度等级**：`高难` | **核心主题**：`Agent, Docker沙箱, 产物审计`
- **可信级别**：项目事实 / 当前代码

> 💡 **一句话速记结论**：
> 沙箱仅开放只读 input 和可写 output，产物必须严格前置声明且校验路径、MIME 与软链接。

##### 🎙️ 30 秒高频口答精要 (电梯演讲 / 直击要害)

沙箱内部严格限制路径：仅允许从只读 `/workspace/input` 读取，向隔离的 `/workspace/output` 写入；调用 `run_python` 时模型必须在 `output_paths` 参数中显式声明将要生成的相对路径（如 `charts/trend.png`）。脚本执行后，系统按清单精准核验文件是否存在，并校验其绝对路径逃逸、MIME 文件类型与软链接；坚决不盲目扫描目录把未声明文件当作产物，防止恶意隐藏脚本外泄。

##### ⏱️ 60~120 秒深度展开 (系统架构 / 机制与推演 / 逐行源码讲解)

Docker 沙箱受限路径规范与显式产物声明（Artifact Manifest）机制：
1. **受限路径拓扑（严格最小权限划分）**：
- `/workspace/input/`（只读挂载 `ro`）：存放本次 Run 注入的已核验 CSV 数据集，脚本只有读取权限，任何写入都会抛出 Permission Denied。
- `/workspace/output/`（可写工作区 `rw`）：脚本唯一合法的产物写入目录。用于输出生成的图表 `chart.png` 或衍生数据 `summary.csv`。
- 其他系统路径（`/etc/`, `/var/`, `/tmp/`）：全部施加只读或临时 tmpfs 挂载，容器退出后立即灰飞烟灭。

2. **为什么系统坚决不“自动扫描目录寻找安全结果”**：
- **混淆与恶意木马写入（Malicious/Garbage Artifact Injection）**：如果系统无脑遍历扫描目录，模型生成代码可能会生成临时的 `dump.core`、无用中间垃圾文件、甚至是尝试写入特洛伊文件，系统无法判断哪个才是用户真正想要的合法图表。
- **缺乏意图契约**：调用参数必须包含 `declared_artifacts: ["sales_trend.png"]`。系统在容器退出后，**只按清单精准提取声明的文件**。如果声明了但未生成，直接判定为执行失败并报错。

3. **核心代码：显式产物契约校验与提取器**：

```python
import os
import shutil
from typing import List, Dict, Any

class SandboxArtifactExtractor:
    def __init__(self, host_output_dir: str):
        self.host_output_dir = host_output_dir

    def extract_declared_artifacts(self, declared_files: List[str]) -> Dict[str, str]:
        """
        按清单定向提取，杜绝全量目录扫描：
        1. 检查声明的文件是否存在
        2. 校验文件扩展名白名单 (.png, .jpg, .csv)
        3. 归档到受控持久化存储
        """
        extracted_manifest = {}
        for fname in declared_files:
            # 安全防线：防止文件名包含 ../ 目录穿越
            safe_name = os.path.basename(fname)
            file_path = os.path.join(self.host_output_dir, safe_name)
            
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"执行异常: 模型声明生成产物 {safe_name}，但沙箱输出目录未找到该文件")

            # 校验扩展名
            ext = os.path.splitext(safe_name)[1].lower()
            if ext not in {".png", ".jpg", ".jpeg", ".csv"}:
                raise PermissionError(f"安全拦截: 产物扩展名 {ext} 不在白名单允许范围内")

            # 提取为合规 Artifact
            extracted_manifest[safe_name] = f"/artifacts/{safe_name}"
            
        return extracted_manifest
```

4. **防坑总结**：显式声明机制强迫大模型在写代码前明确自己的产物交付契约，是实现工业级稳定沙箱的核心支柱。

##### ⭐ 核心关键技术点 (回答骨架)

- ✔️ 容器根系统与 input 目录物理只读挂载，临时输出限定在专用 output 沙箱目录内
- ✔️ 产物必须在 output_paths 显式声明，杜绝盲目目录扫描引入隐藏后门或垃圾文件
- ✔️ 严厉执行路径穿越检查、软链接审查、文件二进制魔数与体积四重防护门禁

##### ❓ 面试官高频追问预判 (连环问攻防对决)

###### 🎯 追问对决：如果模型在代码里向 /workspace/output/ 生成了 1GB 的超大垃圾文件，如何防止宿主机磁盘被打爆？

- 🎯 **考官意图**：考察 Docker 存储配额与临时工作区配额隔离。
- 🛡️ **攻防标准应答**：在创建 Docker 容器时通过存储驱动选项施加磁盘配额，例如 `--storage-opt size=100M`，或者将 `/workspace/output/` 挂载为大小限制为 100MB 的 `tmpfs` 内存文件系统。一旦写入超出配额立即触发 Disk quota exceeded 异常阻断，彻底保护宿主机磁盘。
- ⚠️ **避坑要点**：不要依赖事后脚本去检查文件大小并删除，一旦瞬间写死磁盘会导致整个宿主机所有容器雪崩。

##### 🛡️ 系统设计防御边界与权衡 (Anti-Goals / 放弃的假设)

- 🛑 产物声明仅支持常规图像（.png, .svg）、结构化数据（.csv, .json）与报告（.md），不支持执行文件
- 🛑 容器销毁后，只有通过校验的声明文件会被提升为持久化 Artifact 存入对象存储，其余数据就地粉碎


---
