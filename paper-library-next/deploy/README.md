# 公开阅读与管理入口

在已有 HTTPS `server` 块内 include `public-reading.nginx.inc`，保留原有服务器级 `auth_request`、`/papers/api/` 代理及 `/papers/` 静态位置。本配置适用于静态根目录中含 `papers/index.html`、后端仅监听 `127.0.0.1:4186` 的部署。

| 路径 | 用途 | 访问 |
| --- | --- | --- |
| `/papers/`、`/papers/app.js`、`/papers/style.css` | 文献浏览页面 | 公开 |
| `GET /papers/api/catalog` | 论文展示信息，不含笔记、运行日志、模型设置和服务器路径 | 公开 |
| `GET /papers/api/papers/<SHA-256>/pdf` | 已存在 PDF，支持分段读取 | 公开 |
| `/papers/manage` | 整理、笔记及设置界面 | 继承平台登录 |
| 其他 `/papers/api/` 请求 | 管理操作 | 继承平台登录 |

不要对整个 `/papers/api/` 设置 `auth_request off`。管理入口不加末尾斜杠，使相对脚本和样式路径继续指向 `/papers/`。

发布时备份现有前端、`paperlib/server.py` 和 nginx 配置；先更新后端及两个前端发布目录，再校验 nginx 配置并 reload。后端需重启以加载 Python 变更；重启前确认无运行中的整理任务、每日调度关闭。不得覆盖其他模块的应用、数据库或模型配置。

验证：匿名访问页面和 catalog 应为 200；PDF 的 `Range: bytes=0-4` 应为 206 且正文是 `%PDF-`；匿名访问管理页及 settings/state 应仍被平台登录拦截。校验论文总数、原件和笔记等数据未变化。出现失败时恢复备份，重启论文服务并 reload nginx。
