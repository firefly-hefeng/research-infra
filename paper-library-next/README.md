# 论文管理 · 固定目录子模块

一个直接管理服务器目录的论文管理子模块。页面将待整理区、整理记录和论文列表集中展示，方向、年份、标签和收藏均在列表内筛选，不再设置独立侧栏或工作空间导航。Python 标准库提供 HTTP、SQLite 和调度，原生 HTML/CSS/JS 提供可视化界面；无前端构建步骤，无 Python 第三方包依赖。PDF 文本提取使用 Poppler 的 `pdftotext`。

项目与已有 `../research-platform` 独立，不共享数据库、不修改旧平台。当前默认数据根目录：`/Users/caozheng/Desktop/vesti/papers`。

## 启动与使用

需要 Python 3.9+（Linux 建议 3.11+，并安装系统时区数据）和 Poppler。macOS 可 `brew install poppler`；Debian/Ubuntu 可安装 `python3 poppler-utils tzdata`。

在本目录运行：

```sh
python3 manage.py serve
```

访问 http://127.0.0.1:4186 。macOS 也可双击 `启动论文库.command`。停止服务按 Ctrl+C。所有应用数据位于论文根目录内，代码目录没有隐藏依赖于其他项目的运行状态。

1. 把 PDF 放到 `papers/inbox/`，可以有子目录；大文件先用 `.part` 后缀复制，完成后再改为 `.pdf`。
2. 展开页面顶部“整理工作区”，在“待整理区”点击“扫描新文件”。也可运行 `python3 manage.py scan`。
3. 给你的 agent 指定 [paper-curator skill](skills/paper-curator/SKILL.md)，按 skill 读取原文并生成卡片，通过 `commit` 校验入库。
4. 在同页“全部论文”按标题、作者、内容、标签、笔记搜索；方向、标签和年份可叠加筛选。列表卡片保留标题、作者、年份、简短介绍与标签；点击“阅读论文详情”进入同页阅读视图，展开摘要、贡献、详细解读、原文依据、PDF 和个人笔记。
5. “添加论文”里可导出目录 JSON。PDF 通过原件下载，目录 JSON 不包含 PDF 二进制。

平台支持 **Agent 优先并降级 API、仅 Agent、仅 API** 三种整理方式。实际接入状态以页面“整理设置”为准，定时任务默认关闭。浏览器中的卡片来自持久数据库。

## 目录结构

```text
papers/
├── inbox/                         待整理区
├── library/<主分类>/<年份>/<论文题目>/
│   ├── paper.pdf                  校验后的原件
│   └── card.json                  已校验论文卡片
├── duplicates/<SHA256>/           重复副本，保留不销毁
└── .paperlib/
    ├── catalog.sqlite3            权威目录、个人笔记、收藏、任务日志
    ├── text/<SHA256>.txt           保留换页符的正文缓存
    └── *.lock                     跨进程互斥锁
```

首次兼容根目录已有 PDF 时执行 `python3 manage.py import-root`，它复制到 inbox，保留原文件。普通扫描仅查看 inbox，避免重复扫描整个服务器。内容 SHA-256 唯一，相同内容只创建一张卡片；不同 PDF 版本不会按题名自动合并。入库前验证哈希、证据、复制结果；数据库写入成功后才移走 inbox 副本。已入库卡片再次提交保留原归档位置、收藏和笔记。分类修订以卡片为准，不自动迁移旧目录。

论文独立目录按卡片中的正式题目命名，同一分类、年份下重名时依次为 `论文题目`、`论文题目（1）`、`论文题目（2）`。现存文件、目录、符号链接及数据库保留的路径均算占用，大小写和 Unicode 规范等价的名称也避让。标题中的路径分隔符及不适合文件名的字符替换为空格分隔的短横线，超长目录名截断到 200 个 UTF-8 字节再加编号；卡片保留完整题目。PDF 仍叫 `paper.pdf`，卡片仍叫 `card.json`，内部论文 ID 和去重继续使用 SHA-256。

旧哈希目录可在停止服务和整理进程后运行 `python3 manage.py migrate-titles` 迁移。命令会先校验 PDF、备份 SQLite，并在 `.paperlib/migrations/` 保存旧/新路径映射；然后重命名目录并更新数据库路径，不改动 PDF、卡片、笔记或收藏。普通执行错误会回滚；若被强制中断，按映射和数据库备份核对恢复。重复运行会跳过已迁移的目录。后续修改卡片标题仍保留首次归档位置，不自动再次改名。

## 论文详细解读

详情采用文章式布局，提供阅读目录、研究速览、核心摘要、贡献、背景与问题、方法、实验设计、结果分析与对照表、讨论局限、复现要点和原文资源。只展示卡片中已有的内容；旧卡片继续可读，不因为格式升级而自动生成或重整。

在已归档论文内点击“生成详细解读”（已有解读时为“更新详细解读”），才会按当前通道设置调用 Agent / API。只读取这一篇原文，不扫描待整理区或处理其他论文。页面显示进度并自动刷新，保留笔记草稿。成功后保留原归档位置、收藏和笔记；失败则保留完整旧卡，原因写入任务日志。更新还会检查已有非空解读字段不被遗漏。

可选 `reading` 字段与表格/资源的格式见 [卡片契约](skills/paper-curator/references/card-contract.md)。每个有值的章节都需要对应原文证据；章节下的引用可定位到摘录，再打开对应 PDF 页。链接来自原文，系统不会把它标记为已验证开源或已完成复现。选读长论文仍标记待核对。

## 整理日志在哪里

通过网页“开始整理”或“生成 / 更新详细解读”、每日调度或 `python3 manage.py run` 发起的批次，记录在论文根目录 `.paperlib/catalog.sqlite3` 的 `jobs` 表中。包含任务开始/结束时间、状态、成功/失败篇数，以及逐篇 Agent/API 尝试、切换原因和错误。页面“整理记录”展示最近 40 批，历史记录仍保存在数据库。新任务同时保存独立日志 `.paperlib/jobs/job-<任务ID>.json`，每篇处理后更新进度；失败的卡片及校验诊断保存到 `.paperlib/jobs/job-<任务ID>/<论文ID>-<通道>-<尝试次数>.json`。文件权限 0600，已知 API 密钥会脱敏，不保存请求头或整份请求正文。旧任务的失败卡片无法补回。

手动 `scan`、`extract`、`commit` 的结果输出到命令行，不生成 `jobs` 批次记录。服务自身的 HTTP/运行日志输出到启动终端；systemd 部署时用 `journalctl -u paper-library -f` 查看。Agent 的原始 stdout/stderr 和 API 原始响应不会作为持久日志保存。

## 给 agent 的接口

```sh
python3 manage.py init
python3 manage.py scan
python3 manage.py list
python3 manage.py extract <64位论文ID>
python3 manage.py commit <64位论文ID> /absolute/card.json
```

部署到其他路径时统一设置 `PAPER_ROOT=/srv/papers`，或每个命令都使用 `python3 manage.py --root /srv/papers ...`。skill 是随项目交付的自包含文件夹，可由 agent 显式读取，也可复制到其技能目录；本轮未改用户全局 skill 配置。

卡片的作者、年份和贡献都需要原文依据。校验器核对引用实际存在于指定 PDF 页；这种校验不等于语义正确性审稿。无作者、无年份、版本冲突等情况可保留为“待核对”。OCR 不在当前版本范围，扫描件会明确报错并留在队列。

## Agent 与自定义 API 双通道

`PAPER_AGENT_COMMAND` 是 **JSON 参数数组**，不经 Shell。该命令从 stdin 接收任务 JSON，其中包含 skill、卡片契约、已有标签、论文 ID 和带页码正文；stdout 只能输出单个卡片 JSON；日志输出到 stderr。它是操作者提供的真实 agent 包装命令，不是本项目内置模型。

环境示例见 [.env.example](.env.example)。Agent 命令与调度环境变量修改后需要重启服务：

```sh
export PAPER_AGENT_COMMAND='["/absolute/path/to/your-agent-wrapper"]'
export PAPER_SCHEDULE_ENABLED=1
export PAPER_DAILY_TIME=03:00
export PAPER_TIMEZONE=Asia/Shanghai
python3 manage.py serve
```

也可以在页面的“整理设置”中填写 API Base URL、模型名称和 API Key。接口采用 OpenAI 兼容的 `POST <Base URL>/chat/completions`；例如 Base URL 填 `https://api.example.com/v1`，不要重复填写 `/chat/completions`。支持无密钥的本地服务。API 从服务器直接连接，不继承 Shell 代理，不跟随重定向；浏览器只与论文平台通信。

三种模式：

- `auto`（默认）：逐篇优先使用 Agent。未配置、无法启动、退出异常、超时、JSON 无效或卡片证据校验失败时，尝试已配置的 API。两条通道按顺序执行；Agent 成功就不调用 API。
- `agent`：只调用 Agent，失败后保留论文。
- `api`：直接调用 API，不启动 Agent。

API 和 Agent 都使用同一份 skill、卡片契约、页码正文及已有标签。平台统一校验后归档；磁盘、文件提取或数据库错误不触发模型降级。生成输出或卡片校验失败时，将具体错误和上一版卡片反馈给同一通道，最多修正一次；网络、鉴权、启动错误不作修正重试。API 也失败时保留待整理文件。任务记录包含各通道成功数、切换次数、每篇的尝试顺序及错误原因，校验通过后只提交一次。

API 默认请求 `response_format: {"type":"json_object"}`。若服务或模型不支持，可在页面取消“请求 JSON 模式”；无论是否启用，响应正文都必须是单个合法卡片 JSON，不接受 Markdown 围栏。模型拒绝、输出截断、HTTP 错误和无效卡片都会明确失败。JSON 模式只能帮助保持格式，不能保证卡片语义正确。[接口文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)

页面配置保存在论文根目录 `.paperlib/providers.json`，文件权限为 `0600`，包含明文密钥；服务器备份应保护这个文件。设置接口只返回“是否已保存密钥”，不会返回密钥本身。密钥输入留空表示保留，勾选清除则删除；不保存到浏览器 localStorage。API 错误不记录服务商原始响应。共享密码的使用者都可以修改整理设置，因此远程访问应只提供给可信使用者。

页面保存的通道配置优先于对应环境变量，对下一批任务生效，当前批次使用启动时的配置。保存不会主动启动整理；之后由“开始整理”、CLI 或已启用的调度触发。首次也可使用以下环境变量配置 API：

```sh
export PAPER_PROVIDER_MODE=auto
export PAPER_API_BASE_URL=https://api.example.com/v1
export PAPER_API_MODEL=your-model-id
# PAPER_API_KEY 通过受保护的环境文件或页面填写，不要写入仓库。
export PAPER_API_TIMEOUT=120
export PAPER_API_JSON_MODE=1
export PAPER_AGENT_TIMEOUT=600
```

无需每天重启服务。后台每 20 秒检查一次调度；当天时间已过而尚未触发时补一次，同一日期记录一次尝试。手动点击“开始整理”或执行 `python3 manage.py run` 也可触发。服务需持续运行；建议使用 [systemd 模板](deploy/paper-library.service)。不要再同时叠加 cron。单批最多 50 篇，Agent 默认超时 600 秒、API 默认超时 120 秒（均可设为 1–600 秒）；失败项目保留，下一批可重试。中断后再次执行会以文件哈希跳过已成功项。正文按物理 PDF 页拆为带 SOURCE 编号的连续片段，自动输入上限为 160,000 字符（含标记）。长论文优先提供前 12 页、结论/讨论/实验/局限标题所在页及其后页，再按顺序补齐预算；保留原始页码并记录覆盖范围。只要有遗漏就强制标记待核对，可用手动 skill 分段读全文后补齐。模型优先用 source_id 引用片段，由平台填入逐字原文及页码，继续执行严格校验；不使用模糊匹配放行伪造引文。

agent 是服务器管理员选择的外部可执行程序；它拥有其运行账户的权限，本系统的目录校验不是该程序的操作系统沙箱。建议让服务与 agent 使用仅能访问论文库的独立账户。若接入远程模型，论文正文会由 Agent 包装命令或 API 通道发送给配置的模型服务。

## 服务器部署

参见 [部署说明](deploy/README.md)。默认只监听本机。远程监听要求至少 12 位 `PAPER_PASSWORD`，并设置访问地址 `PAPER_PUBLIC_ORIGIN`。所有用户共享同一论文库、收藏和笔记；当前提供共享密码，不是多人角色权限系统。

HTTP API：`GET /api/state`、`GET/PATCH /api/settings`（通道配置，密钥只写不读）、`POST /api/scan`、`POST /api/run`、`POST /api/papers/<id>/reading`（仅更新指定归档论文）、`PATCH /api/papers/<id>`（notes/favorite）、`GET /api/papers/<id>/pdf`、`GET /api/export`、`GET /api/skill`。写入要求 JSON 和 `X-Paper-Library: 1`，并拒绝跨站 Origin。启用密码后先通过 `POST /api/login` 获取 HttpOnly 会话 Cookie。PDF 支持 Range，未知文件路径不会被开放。

## 备份、边界与测试

停服务并确保无 agent 正在整理，再复制**完整 papers 目录（包括隐藏的 .paperlib）**。恢复后设置 PAPER_ROOT 并启动即可。单独复制 library 下的 card.json 不包含个人笔记和收藏，不能替代完整备份。

扫描跳过符号链接与最近 3 秒仍在写入的文件；单个 PDF 上限 256 MiB，文本缓存上限 8 MiB。仅允许同一根目录运行一个服务。磁盘文件被其他程序删除时，页面提示原件缺失。请不要在任务运行时从外部改写归档目录或数据库。一个共享密码对应共享读写权限；尚不支持每人独立笔记、权限分组、自动 OCR、语义向量检索和远程上传。

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js
```

测试使用临时目录和临时服务端口，不污染真实论文库。涵盖归档哈希、重复副本、错误证据、缺年份、符号链接、路径越界、未完成写入、文件变化、笔记持久化、CLI、agent 成败日志、并发锁、HTTP 登录、跨站校验和 PDF Range。双通道测试还覆盖优先级、超时降级、证据校验降级、无效响应、密钥持久化与不回传、重定向拒绝，以及归档异常不重复调用。测试使用本机模拟 API，不会访问真实模型服务。
