# RMP-OPS-20261128-SERVER-PLATFORM-AUDIT

## 范围与方法

核验时间：2026-11-28 03:59（Asia/Shanghai）。类型：只读工程核验，不是科研实验。

通过用户授权的服务器账号连接 `101.132.97.146` 与 `47.117.138.84`，只读取主机时间、systemd 单元、监听端口、部署路径、指定程序文件校验值及回环 GET 响应；另从公网无凭据请求 MCP discovery 和 `/mcp`。未读取环境密钥、配置密码、Cookie、OAuth 数据库或报告附件，未写文件、安装软件、重启服务或发布代码。

## 结论摘要

- 网站入口、门户、进度、文献和飞书网关目前都在 `101.132.97.146` 运行；`47.117.138.84` 本轮只发现 `research-workspace-read.timer` 等相关单元，没有平台 Web 监听，符合资源/工作区节点而非网站入口的定位。
- 线上进度数据与 `origin/main` 的 2026-11-22 方向方法实现一致；本轮三级金字塔和六类算法核心地图**尚未发布**。
- 仓库已有远程 MCP 实现与部署样例，但生产机当前**没有安装或运行 `research-progress-mcp.service`**，8772 未监听，Nginx 无 MCP 配置，公网 discovery 与 `/mcp` 均跳转飞书登录。因此不能把仓库中的远程 OAuth MCP 描述当成已可用的线上能力。

## 101.132.97.146 实际运行

| 项目 | 实测状态 |
| --- | --- |
| 门户 | `research-data-center.service` active/running；执行 `/opt/research-data-center/releases/20261111-compute-history-v1/server.py`，工作根 `/var/lib/research-data-center/workspace`，监听 127.0.0.1:8765 |
| 进度 | `research-weekly-web.service` active/running；工作目录 `/data/rmp/research-progress`，监听 127.0.0.1:8766 |
| 文献 | `paper-library.service` active/running；工作目录 `/data/rmp/paper-library`，监听 127.0.0.1:4186 |
| 统一入口 | `research-platform-nginx.service` 与 `research-platform-auth.service` active/running；80/443 监听 |
| 定时维护 | 算力历史、冷备份、入库、服务器监控、共享权限、周报收件/汇总和工作区读取的 timer 均 active；一次性 service 平时 inactive/dead 属正常调度状态 |
| MCP | `research-progress-mcp.service` LoadState=not-found；无对应 unit file；127.0.0.1:8772 connection refused；生产 Nginx 配置未出现 `mcp` 或 `8772` |

回环 GET 实测：

- `/api/agent/manifest` 返回 200，版本 `1.3`，没有 `mcp` 字段。
- `/api/direction-methods` 返回 200：`published`，证据整理日期 2026-11-22，18 个方向、39 项方法、106 条引文、55 份原始来源。
- 默认 reviewed `/api/lab-review?format=json` 返回 200：生成于 2026-11-20T18:19:43Z，8 位成员、11 个主题、30 个来源，`available_versions` 为 reviewed/auto。
- `/papers/api/state` 返回 200。
- 进度模块的 `direction_methods.py`、`lab_review_page.py`、`direction-methods.html`、`lab-review.css` 与当前 `origin/main` 对应文件 SHA-256 完全一致；本地本轮版本已不同，未发布。

公网无凭据实测：

- `/.well-known/oauth-protected-resource/mcp`：302 到 `/auth/login`。
- `/.well-known/oauth-authorization-server/mcp/oauth`：302 到 `/auth/login`。
- `/mcp`：302 到 `/auth/login`。

这些结果不符合 MCP 公共 discovery 应免登录、无 token `/mcp` 应返回 401 的验收标准。需要单独部署 MCP 服务、Nginx include 和飞书网关补丁后，再按 `docs/progress-mcp.md` 做真实成员授权验收。

## 47.117.138.84 实际运行

- 发现 `research-workspace-read.service`（inactive/dead，等待定时触发）和 `research-workspace-read.timer`（active/waiting）。
- 未发现研究平台、论文、飞书或 Nginx 相关运行单元，也未发现 80、443、4186、8765、8766、8772 监听。
- 历史部署记录中的门户路径在该机不存在；不把它误记为第二网站入口。

## 后续边界

本轮服务器内容保持原样。代码推送到 GitHub 不等于生产发布；三级金字塔、算法核心地图、新快照字段和运行时 MCP 合同仍需经独立发布窗口部署。远程 MCP 在单元、端口、Nginx、discovery、真实成员 OAuth、刷新/撤销/退出与续验全部实测通过前，状态保持“代码已具备，线上未开通”。
