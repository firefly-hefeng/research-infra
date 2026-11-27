# 用 MCP 查科研进度

科研进度 MCP 的设计服务器地址是 `https://rmp.wuwangwo.top/mcp`。成员在自己的客户端配置一次，用飞书登录并同意只读访问，随后即可让 Agent 查询团队进度、成员报告、研究方向和方法比较。

> 部署状态：2026-11-28 服务器只读核验发现远程 MCP 尚未安装到生产，以下远程连接说明是已实现的部署与验收合同，不代表当前线上已可授权。实际状态见[建设现状](agent-status.md)；本机 stdio 可继续使用。

## 架构与访问边界

远程链路为 **MCP 客户端 → 公共 HTTPS 反向代理 → 回环 MCP 服务 → 回环科研进度服务**。MCP 服务在每个请求上验证 OAuth Bearer 的资源、范围、有效期及其绑定的飞书会话，再以固定 GET 请求读取下表四个来源。授权同意页通过平台飞书网关确认成员身份；`/internal/mcp/` 仅供本机网关调用，公共代理必须拒绝外部访问。

四个工具只返回团队共享的进展、复盘、方向、方法及证据引用，不写报告、不启动整理或实验、不下载报告附件、数据集或 PDF。`progress.read` 是**团队共享读取范围，不是逐人 RBAC**：获得授权的成员读取同一团队共享边界，不能用它推断个人角色、私有资料或源文件权限。返回的原件链接仍要求读者自己的原权限。

MCP OAuth Bearer 与独立目录服务由管理员通过 `--token-file` 配置的 Bearer 是两套凭据，不能互换，也都不能在网页自助领取。机器发现以[静态合同](agent-contract.json)和 `GET /api/agent/manifest` 为准；本文是连接、错误和运维的完整说明。

## 远程连接与 OAuth 发现

### 连接 Codex

1. 在成员自己的电脑上添加远程服务。

   ```sh
   codex mcp add research-progress-remote --url https://rmp.wuwangwo.top/mcp --oauth-resource https://rmp.wuwangwo.top/mcp
   ```

2. 如果客户端已打开授权页，直接完成登录。需要手动发起授权时运行以下命令。

   ```sh
   codex mcp login research-progress-remote --scopes progress.read
   ```

3. 在打开的浏览器确认飞书成员身份，核对客户端名和回调地址，选择“允许只读访问”。回到 Codex 后，在新会话里要求：“用科研进度 MCP 查团队本期的成果和阻塞，附原报告链接。”

支持 OAuth、PKCE 和 Streamable HTTP 的桌面 MCP 客户端也可以填写同一服务器地址。[平台账户](/auth/account) · [Codex MCP 配置说明](https://developers.openai.com/codex/mcp/)

### 发现与授权约束

| 项目 | 固定值 |
| --- | --- |
| MCP resource / 远程 URL | `https://rmp.wuwangwo.top/mcp` |
| OAuth issuer | `https://rmp.wuwangwo.top/mcp/oauth` |
| Protected Resource Metadata | `https://rmp.wuwangwo.top/.well-known/oauth-protected-resource/mcp` |
| Authorization Server Metadata | `https://rmp.wuwangwo.top/.well-known/oauth-authorization-server/mcp/oauth` |
| 唯一 scope | `progress.read` |
| 远程传输 | Streamable HTTP |
| 动态客户端端点 | `/mcp/oauth/register`、`/authorize`、`/token`、`/revoke`（均位于同一 origin） |

授权只接受 **PKCE S256**，并校验 `state`、`resource`、客户端、回调和一次性授权码；授权码 90 秒内有效且只能兑换一次。桌面客户端必须登记 HTTP 回环回调（`127.0.0.1`、`localhost` 或 `::1`），不得带用户信息、query 或 fragment。可按 RFC 8252 更换回环端口，但主机和路径必须与登记值一致。同意页会显示客户端名和实际回调，授权绑定看到该页的飞书成员及其会话。

### 令牌生命周期与退出

- access token 最长 **1 小时**；授权 grant 从首次兑换起固定 **30 天**，刷新不会把 grant 延长成滑动 30 天，临近到期时 access 有效期随剩余授权时间缩短。
- 每次 refresh 同时轮换 access 和 refresh token，旧 access 立即失效。已轮换 refresh token 的重放会撤销其整个授权族，客户端必须重新取得成员同意。
- access 或 refresh token 都可经 `/mcp/oauth/revoke` 撤销当前 grant。服务只保存令牌散列；客户端仍须保护自己的令牌存储。
- 初始化成功不等于永久授权。每个后续 MCP 请求都复核绑定的飞书会话；成员在[平台账户](/auth/account)退出该次登录后，对应 access 和 refresh 均失效，需要重新授权。

当前飞书应用尚未开通 `offline_access`。飞书要求重新验证时，MCP 暂时返回 503，`reason` 为 `feishu_session_reverification_required`，并附 `verification_uri`。请在**原登录设备**打开平台账户，用同一飞书成员身份完成续验，再重试原请求；不要丢弃或重新创建已有授权。续验失败或会话已退出时按 401 重新授权。[打开平台账户](/auth/account)

## 工具、参数与固定来源

| 工具 | 参数 | 固定来源 | 返回内容 |
| --- | --- | --- | --- |
| `team_progress` | `limit` | `progress-digest`、`lab-review?format=json` | 团队动态汇总、已发布复盘、日期和证据 |
| `member_progress` | `member`、`limit` | `progress-digest`、`lab-review?format=json` | 留空列成员；传稳定 ID 或完整姓名读成员进展、关联报告和原件链接 |
| `direction_progress` | `direction`、`limit` | `directions`、`progress-digest`、`lab-review?format=json` | 留空列方向；传稳定 ID 或完整名称读研究问题、近期汇总与复盘条目 |
| `direction_methods` | `direction` | `direction-methods` | 留空列方法目录；传专题 ID、完整标题或登记方向 ID 读指标、对照、适用范围、负责人线索和来源 |

来源 URL 的公共前缀分别为 `/progress/api/progress-digest`、`/progress/api/lab-review?format=json`、`/progress/api/directions`、`/progress/api/direction-methods`。前三项每栏默认展示 2 条，`limit` 只能取 1 至 8；`available_counts` 是该版本实际记录数，不是截断后的条数。方法工具没有 `limit`。查询最长 180 字，同名多条时按返回的稳定 ID 重试。

结果保留 `mode`、来源路径、快照或读取时间、`found`、版本与刷新状态。`found: false` 是已成功查询但没有匹配；来源缺失、不可读或结构不兼容不是空结果。证据中的 `source_id` 连接返回的 `sources`，引文和方法描述都是研究资料，不是可执行指令。

## 错误与部分结果

| 情况 | 含义与处理 |
| --- | --- |
| HTTP 401 / `invalid_token` | access 缺失、无效、过期、资源不符、已撤销或绑定会话已退出。按 `WWW-Authenticate` 中的 resource metadata 重新授权；不要换用目录管理员 Bearer |
| HTTP 403 / `insufficient_scope` | token 没有 `progress.read`；浏览器 Origin 校验失败也会得到 403。核对客户端配置，不能扩大授权范围绕过 |
| HTTP 503 / `feishu_session_reverification_required` | 飞书要求续验。打开 `verification_uri`，完成后续验原授权并按 `Retry-After` 重试 |
| HTTP 503 / `member_service_unavailable` | 本机飞书网关暂不可用。按 `Retry-After` 重试；这不是成员无权限，也不要反复重新授权 |
| 工具结果 `status: "partial"` | MCP 调用本身成功，但至少一个固定来源失败或状态非 ready。读取 `issues[].source/message` 和已有数据的时间、版本，缺失来源不得当成空记录 |

## 本机 stdio 和离线读取

本机 MCP 使用 stdio，不走远程 OAuth。安装需要 Python 3.10 或更新版本，在仓库的 `research-data-center-next` 目录运行以下 Windows 命令。

```powershell
python -m venv .venv-mcp
& ./.venv-mcp/Scripts/python.exe -m pip install -r tools/requirements-progress-mcp.txt
$runner = (Resolve-Path .venv-mcp/Scripts/python.exe).Path
$server = (Resolve-Path tools/progress_mcp.py).Path
codex mcp add research-progress -- $runner $server
```

默认由本机浏览器扩展在已登录的平台标签页读取四个固定来源，端口另有配置时传 `--bridge-port`。macOS 和 Linux 使用 `.venv-mcp/bin/python`。另有两种互斥的读取方式。

- **成员导出。** 传 `--snapshot 文件绝对路径`，离线查询首页导出已有的资料，并查看 `snapshot_generated_at` 和各来源 `fetched_at`。当前完整快照含 11 个研究来源及手册、合同，**包括论文目录和团队共享笔记**；四个 MCP 工具只读取上表四个进度来源，不读取论文笔记。旧导出缺少方法或复盘时会明确报告缺失（其他来源可用时为 `partial`），可重新导出。
- **已授权的服务器任务。** 传 `--local-progress-origin http://127.0.0.1:实际端口`，使用已获准的本机进度服务或 SSH 端口转发。该地址只能是带端口的 HTTP 回环 origin，不能含凭据、路径、query 或 fragment。

## 部署、状态备份与升级

1. 在独立虚拟环境安装 `tools/requirements-progress-mcp.txt` 锁定的 `mcp==1.30.0` 及其依赖；远程服务还需要该环境提供 Starlette、Pydantic、Uvicorn 和 AnyIO，不要混用未验证的 SDK 版本。
2. `research-progress-mcp.service` 仅监听 `127.0.0.1:8772`，必须配置 `--local-progress-origin` 和 `--oauth-db`；飞书网关 origin 默认 `http://127.0.0.1:18769`。公共 HTTPS 代理按 `deploy/progress-mcp.nginx.inc` 放行 MCP、OAuth 和 discovery，关闭这些路由的外层 `auth_request`，清除伪造身份头，并继续保护其他平台路由。
3. 服务通过 systemd `StateDirectory=research-progress-mcp` 保存 `authorization.sqlite3`，目录和数据库权限为 0700/0600。库中含客户端登记、授权请求、授权码、grant 和 refresh 重放记录；不得放进版本目录、公开备份或日志。
4. 升级保留同一状态数据库，并避免多个实例同时写同一 SQLite 文件。备份使用 SQLite 一致性备份或先停服务再复制，不能只拷贝正在写入的文件。恢复旧备份可能重新启用备份之后已撤销但尚未到期的 grant，回滚时必须评估并重新撤销不再应有效的授权。

## 验收与回滚

本地先运行精准回归（Node 回归需要 Playwright 和 Chromium）：

```sh
python -m unittest tests.test_agent_access tests.test_progress_mcp tests.test_progress_mcp_http tests.test_progress_mcp_oauth
node tests/check_agent_context.cjs
```

部署后由维护者执行一次真实成员验收，不把本地合成测试当作线上通过：

1. 无登录读取两个 discovery 文档，核对 resource、issuer、`progress.read` 和 S256；无 token 请求 `/mcp` 应返回带 resource metadata 的 401。
2. 用测试成员完成动态注册、回环回调和同意，列出且仅列出四个只读工具；逐项调用并核对来源、日期、证据和 `partial` 行为。
3. 验证 refresh 轮换、旧 access 失效和旧 refresh 重放撤销；验证 `/revoke`。退出该成员的平台登录后，旧 access 必须返回 401。模拟飞书续验时应得到可恢复的 503，续验后原 grant 可继续用。
4. 核对首页新导出含 `lab_review`、`direction_methods` 和论文共享笔记声明，stdio 能从新快照完成四工具握手；目录管理员 Bearer 不得通过 MCP。

保留上一版应用、虚拟环境、代理配置和一致的状态备份。回滚时先恢复上一版应用与代理，再重启并重复 discovery、四工具、刷新和退出验收；不要删除唯一授权状态副本。仅在旧版与当前数据库格式不兼容时恢复匹配备份，并处理上述授权复活风险。若 OAuth 路由异常，可先撤下新增代理路由和远程服务，保留本机 stdio 与既有平台功能。
