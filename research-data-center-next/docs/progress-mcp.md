# 用 MCP 查科研进度

在浏览器打开[团队进展](/progress/#team)，用成员的飞书账户登录。Agent 可以直接查询团队、成员、方向和方法。响应包含报告日期、可用的原件链接和证据摘录。浏览器扩展只对平台执行预设的同源 GET，登录凭据留在浏览器。

## 一次性配置

需要 Python 3.10 或更新版本。以下 Windows 命令在 `research-data-center-next` 目录运行，把服务注册到本机 Codex。使用其他 MCP 客户端时，将同一个 Python 解释器填为 stdio 启动程序，脚本绝对路径填为第一个参数。

```powershell
python -m venv .venv-mcp
& ./.venv-mcp/Scripts/python.exe -m pip install -r tools/requirements-progress-mcp.txt
$runner = (Resolve-Path .venv-mcp/Scripts/python.exe).Path
$server = (Resolve-Path tools/progress_mcp.py).Path
codex mcp add research-progress -- $runner $server
```

默认使用本机已连接的 Kimi Browser Extension 和已打开的科研平台标签页。浏览器端口另有配置时，在脚本之后加 `--bridge-port 端口号`。macOS、Linux 使用虚拟环境中的 `.venv-mcp/bin/python`。该服务由客户端按需启动，采用[官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)的 [MCP 标准输入输出协议](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)。

## 常用问题

| 想了解什么 | 工具 | 读到什么 |
| --- | --- | --- |
| 团队近期推进到哪里，还有哪些阻塞？ | `team_progress()` | 动态汇总与已发布团队复盘，各自列出日期、来源和建议依据 |
| 一位成员本期做了什么？ | `member_progress()`，再用返回的 ID 调用 `member_progress(member="…")` | 同 ID 成员的进展、证据和在期内关联的报告数 |
| 某方向有哪些基线与近期证据？ | `direction_progress()`，再用方向 ID 调用 | 登记的研究问题、近期汇总及明确关联该方向的复盘条目 |
| 比较了哪些方法，用了什么指标？ | `direction_methods()`，再用目录条目 ID 或登记方向 ID 查询 | 方法、结果、指标、对照、适用范围和来源 |

前三项默认每栏显示 2 条，可传 `limit=1` 至 `8`。返回的 `available_counts` 表示对应版本的栏目条数。使用来源 ID 查原件。团队复盘中的“模型建议”和“已报告计划”沿用来源标记。方法和近期进展分别查询，基线成果与本期新发现各有各的证据。

## 其他读取方式

- **已有成员导出**。脚本参数加 `--snapshot 成员上下文文件的绝对路径`，可离线查阅导出时已有的来源。响应附导出时间。旧导出可能没有团队复盘或新版方法目录。
- **已授权的服务器任务**。脚本参数加 `--local-progress-origin http://127.0.0.1:实际端口`，查询现有本机进度服务或已经授权的本地转发。地址由服务维护者提供。

发现工具后先调用 `team_progress`。飞书过期时回到科研平台续登后重试。某个来源不可用时，成功资料与失败原因会同时返回，状态为 `partial`。全部必需来源缺失时，MCP 返回工具错误。新版方法接口尚未发布的环境会明确返回 HTTP 404。
