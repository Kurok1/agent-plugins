---
name: python-project-patterns
description: 当用户在一个Python项目中工作时，应当遵循的结构化工程规范
metadata:
  short-description: Python 项目标准工程化规范（结构/入口/依赖）
---

# Python 项目工程化规范（Codex Skill）

## 目标
为Python 项目提供接近 Java 工程化体验的标准：可复用包结构、明确入口、可锁定依赖。

## 总体原则（必须遵循）
1. **src-layout**：可复用代码必须在 `src/<package_name>/` 下，避免“本地能 import，发布后崩”的隐患。
2. **入口与业务分离**：入口只负责参数解析/装配依赖；业务逻辑下沉 `core/`，可测试可复用。
3. **pyproject.toml 单一事实源**：依赖、构建、工具配置集中在 `pyproject.toml`，配套 lock 文件。
4. **分层**：core（纯业务）/adapters（外部系统）/cli（入口）/config（配置）。
5. **质量门禁**：至少包含格式化、lint、测试；推荐类型检查与 pre-commit。

---

## 标准目录结构（模板）
将 `<proj>`、`<pkg>` 替换为实际项目名与包名（通常一致但建议包名用 snake_case）。

```text
<proj>/
├─ pyproject.toml
├─ README.md
├─ LICENSE
├─ .gitignore
├─ src/
│  └─ <pkg>/
│     ├─ __init__.py
│     ├─ __main__.py        # 支持 python -m <pkg>（推荐）
│     ├─ cli.py             # CLI 入口（推荐）
│     ├─ config.py          # 配置与常量（可选）
│     ├─ core/
│     │  ├─ __init__.py
│     │  └─ ...
│     ├─ adapters/
│     │  ├─ __init__.py
│     │  └─ ...
│     └─ utils/
│        ├─ __init__.py
│        └─ ...
├─ tests/
│  └─ test_*.py
└─ scripts/                 # 一次性脚本/运维脚本（不作为包入口）
```

## 入口规则
* src/<pkg>/cli.py：必须提供 main()，作为 CLI 主入口
* src/<pkg>/__main__.py：必须调用 cli.main()，以支持 python -m <pkg>
* 禁止把核心逻辑堆在 cli.py：cli 只做参数与依赖装配，然后调用 core

## 依赖管理路线（默认选择其一）
> 你在执行任务时，优先选择“当前项目已在用”的路线；默认选 uv（更快），如果提示uv命令未找到，则改用pip方式

### 路线 A：uv（推荐默认）

* pyproject.toml 写依赖
* uv.lock 锁定依赖

常用命令：
* uv sync：安装依赖到虚拟环境
* uv run <cmd>：在环境中运行命令
* uv add <pkg>：添加依赖
* uv add --dev <pkg>：添加开发依赖

### 路线 B：pip（成熟稳定保底）

常用命令：

* pip install <pkg>
* pip install <pkg> --index-url https://pkg.site/path/to/whl

### requirements.txt 的定位

允许作为 导出/部署产物（例如导出冻结依赖用于某些运行环境）

不建议作为“唯一源头”；源头应是 pyproject.toml + lock


## 代码模板（最小可运行）
**src/`<pkg>`/cli.py**

* 规则：只解析参数与调用 core，不写业务细节。
```python
from __future__ import annotations

import argparse
from .core.app import run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="<proj>", description="CLI utility.")
    p.add_argument("--dry-run", action="store_true", help="Do not perform side effects.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(dry_run=args.dry_run)
```

**src/`<pkg>`/main.py**
```python
from .cli import main

raise SystemExit(main())
```

**src/`<pkg>`/core/app.py**
```python
from __future__ import annotations

def run(*, dry_run: bool = False) -> int:
    # TODO: implement business logic
    if dry_run:
        print("dry-run: no changes made")
    else:
        print("running...")
    return 0
```


## 常见改造路径（从“脚本堆叠”迁移到工程化）
当你发现项目像这样：

* 根目录一堆 xxx.py
* 入口脚本里混杂业务逻辑
* 依赖靠手写 requirements 或随手 pip install

按以下顺序改造（必须按序做，降低风险）：

1. 创建 src/<pkg>/ 并迁移可复用逻辑到 core/
2. 增加 cli.py + __main__.py，保证双入口可跑
3. 引入 pyproject.toml 与 lock（确保环境有uv）