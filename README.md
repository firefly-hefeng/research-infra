# research-infra · 科研管理平台

本仓库是课题组科研管理相关组件的合集，代号 `research-infra`（科研基础设施）。它把文献管理、科研资源门户、团队周报/日报等能力拆分为可独立运行的子模块，共享同一套“Agent 辅助 + 人工校验”的工作方式。

> 当前为内部基础组件合集，各模块仍在持续迭代。部署到生产环境前请检查对应子模块的 README 和部署文档。

## 仓库结构

```text
.
├── paper-library-next/          # 论文库：PDF 归档、阅读笔记、Agent/API 双通道整理
├── research-data-center-next/   # 科研资源与协作门户：数据/模型/算力/来源导航
├── research-progress-next/      # 科研周记：成员登记、日报/周报上传、Agent 周报汇总
├── research-data-center/        # 资源中心旧版（保留兼容）
├── 海报与图表素材/              # 宣传海报与数据图表生成脚本
├── docs/                        # 跨模块文档
├── 数据/                        # 公共数据目录（按需使用，不提交大文件）
└── README.md                    # 本文件
```

## 核心模块

### 1. paper-library-next · 论文库

直接管理服务器目录的论文管理子模块。将待整理区、整理记录和论文列表集中展示，支持方向、年份、标签、收藏筛选；原生 HTML/CSS/JS 前端，Python 标准库提供 HTTP、SQLite 与调度，无前端构建步骤。

- 启动：`python3 manage.py serve`
- 默认地址：http://127.0.0.1:4186
- 支持 Agent / API 双通道自动整理、PDF 原文证据校验、详细解读生成
- 详见 [paper-library-next/README.md](paper-library-next/README.md)

### 2. research-data-center-next · 科研资源与协作门户

面向组内的公共资料目录、服务器资源入口、科研进度和研究来源导航。普通成员从四份指南开始；完整数据集/模型说明、协议清单和发布版本由管理团队维护。

- 启动：`python server.py --db var/catalog.sqlite3 --host 127.0.0.1 --port 8765`
- 提供 `/api/summary`、`/api/assets`、`/api/research-guide` 等只读接口
- 详见 [research-data-center-next/README.md](research-data-center-next/README.md)

### 3. research-progress-next · 科研周记

无需登录的成员登记 + 日报与周报系统。成员选择姓名后即可在线填写或上传 Markdown；Agent 每周收集标准周报并发布团队概要及逐人进展。

- 启动：`.venv/bin/python -m research_weekly.cli serve`
- 默认地址：http://127.0.0.1:8765
- 详见 [research-progress-next/README.md](research-progress-next/README.md)

## 快速开始

各子模块依赖独立，请分别进入目录按各自 README 初始化。

```bash
# 论文库
cd paper-library-next
python3 manage.py serve

# 科研资源门户
cd research-data-center-next
python server.py --db var/catalog.sqlite3 --host 127.0.0.1 --port 8765

# 科研周记
cd research-progress-next
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m research_weekly.cli demo
.venv/bin/python -m research_weekly.cli serve
```

## 部署提示

- 当前生产版本、域名、模块路径、三机 GPU 监控和验收记录见 [科研平台部署说明（2026-10-29）](docs/科研平台部署说明_20261029.md)。
- 论文库默认只监听本机，远程访问需设置 `PAPER_PASSWORD` 和 `PAPER_PUBLIC_ORIGIN`。
- 科研周记默认无登录，适用于团队内网或已有网络访问边界。
- 资源中心的数据库、锁文件等不要放在 NFS/OSS 上。
- 不要把密码、访问令牌或私有诊断写入源码、文档或公开导出。

## 开发与测试

各模块均自带测试，进入对应目录运行：

```bash
# paper-library-next
python3 -m unittest discover -s tests -v
node --check web/app.js

# research-data-center-next
python -m unittest discover -s tests -v
python tools/check_docs.py

# research-progress-next
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --check web/app.js
```

## 许可证

内部科研基础组件，暂按课题组内部使用管理。如需对外发布，请单独确认各子模块依赖与数据授权。
