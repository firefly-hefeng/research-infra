# 科研管理平台

`research-infra` 包含科研资源门户、团队进度和文献库。成员从科研工作台进入生产环境。首次接手、查找数据或维护平台时，先读平台说明。

[打开科研工作台](https://rmp.wuwangwo.top/) · [平台说明](docs/platform-guide.md)

| 常用任务 | 入口 |
| --- | --- |
| 查数据、模型和飞书来源 | [数据与模型](https://rmp.wuwangwo.top/#data-platform) · [资源中心 README](research-data-center-next/README.md) |
| 填写日报、提交周报 | [日报](https://rmp.wuwangwo.top/progress/#daily) · [周报](https://rmp.wuwangwo.top/progress/#upload) · [进度模块 README](research-progress-next/README.md) |
| 查团队进展和方法证据 | [团队进展](https://rmp.wuwangwo.top/progress/#team) · [方向与方法](https://rmp.wuwangwo.top/progress/direction-methods) |
| 阅读论文和团队文档、查看算力 | [文献库](https://rmp.wuwangwo.top/papers/) · [原点文档](https://rmp.wuwangwo.top/#documents) · [服务器资源](https://rmp.wuwangwo.top/servers) |
| 用 Agent 查进展 | [科研进度 MCP](research-data-center-next/docs/progress-mcp.md) |

生产工作台、成员进度和管理入口使用飞书身份。文献库的公开阅读与成员管理入口各有访问条件。成员和 Agent 都应沿报告、资料版本或论文原文核查关键结论。

## 本地开发

从干净检出启动三个应用，可按[本地联调说明](dev/README.md)安装依赖后打开 `http://127.0.0.1:18081/`。本地运行使用演示成员、仓库内的目录快照和独立工作目录。

| 子目录 | 用途 | 开发说明 |
| --- | --- | --- |
| `research-data-center-next/` | 科研门户、资料目录、算力和来源入口 | [资源中心](research-data-center-next/README.md) |
| `research-progress-next/` | 日报、周报、团队进展、方向与方法 | [进度模块](research-progress-next/README.md) |
| `paper-library-next/` | 论文检索、归档和导读 | [文献模块](paper-library-next/README.md) |
| `research-data-center/` | 历史资源中心 | [旧版说明](research-data-center/README.md) |

## 维护

资料登记、迁移和旧路径核验见[共享数据维护流程](research-data-center-next/docs/storage-catalog-workflow.md#7-冷盘迁移与飞书台账)。历史配置和版本见[部署归档](docs/科研平台部署说明_20261029.md)。提交公开仓库前，检查本次改动使用通用配置或合成数据。生产路径、访问凭据和原件回执由团队各自的工作区保管。
