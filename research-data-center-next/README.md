# 科研资源门户

[使用入口](docs/README.md) · [数据与模型](docs/data/README.md) · [团队方向与进展](docs/progress/README.md) · [基础学术委员会](docs/research-council.md)

该模块提供统一首页、分类资料浏览、服务器状态、研究成果和文书阅读。文献与科研进度是独立应用，分别从 `/papers/` 和 `/progress/` 进入。按模块更新可以沿用原资料 ID 和页面链接。

## 本地运行

```sh
python catalog.py import --db var/catalog.sqlite3 --input data/catalog.json
python server.py --db var/catalog.sqlite3 --host 127.0.0.1 --port 8765
python -m unittest discover -s tests -v
python tools/check_docs.py
```

Agent 先读 [统一手册](docs/agent-guide.md)、[建设现状](docs/agent-status.md)，再从 `/api/agent/manifest` 发现接口。线上使用飞书登录，无成员自助 Agent token；无法访问浏览器时可在首页 Agent 区下载上下文，或使用已授权服务器连接。日常读 `/api/platform/library` 和 `/api/workspace-docs`，需要底层证据时读取 `/api/resource-mapping/{registry_id}`。首页复用 `/progress/api/progress-digest` 展示近期团队与全员动态进展，展开后回查来源。

## 维护入口

- 资料分类和描述见 [data/README.md](data/README.md)。飞书查看权限和增量刷新见[飞书台账刷新](docs/feishu-library-sync.md)。
- 原始目录和研究成果继续使用现有 JSON 清册与证据。资料原件的接收见[现有入库协议](docs/agent-protocol.md)。
- 成员工作区和成员共享区的普通新文件默认可互读。持续维护与实机测试见[新建文献长期互读](experiments/2026-11-23-new-document-readability.md)。
- 运维读取[部署与恢复](deploy/SHARED-MANAGEMENT-OPERATIONS.md)、[监控细节及历史说明](docs/portal-history.md)。活跃 SQLite 在本机磁盘，服务继续绑定回环地址。
