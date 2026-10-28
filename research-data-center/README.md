# 科研数据统一管理中心

一期提供本地持久化的公共科研资源目录：完整纳入原 `/data/datasets` 与 `/data/models` 所对应的两类公共资料库（CPFS canonical 目标为 `/data/share/datasets`、`/data/share/models`，复制期间仍使用旧来源），展示已有台账、目录发现与模型元数据。公共区中的原件、衍生特征、标注、业务数据及研究集合均纳入；不扫描成员工作目录。实际条目数以首页和 `/api/summary` 为准，记录数不是独立数据集或样本数。

服务器部署目录：`/data/rmp/research-data-center`。SQLite 元数据、导入来源和源码均落盘；资料当前所在位置以迁移回执及逐项映射为准。无需第三方 Python 依赖，不占 GPU。

2026-10-27 已启动将两库迁往 CPFS 的操作，目标为 `/data/share/datasets` 和 `/data/share/models`。复制和校验期间旧位置继续提供资料；只有两库核验及路径切换回执齐全时，目录才激活新位置。旧路径将保留兼容软链接，已验证的本地旧副本按本次授权清理以释放容量。操作记录和完整文件清单保存在服务器应用的私有 `var/cpfs-migration-20261027/`；当前进度以首页和 `data/path-migration.json` 为准，不能把本段说明当作已完成回执。

[三机共享数据与实验规范](docs/cpfs-team-guide.html) 涵盖下载、增补、审核发布、共享缓存及个人实验；个人空间复用既有 `/data/share/public/<username>`。其中协调器、队列与自动发布是待实施机制。原始资料、在线 SQLite 和可写下载缓存需要区分，当前 NFS 挂载不提供可靠的跨机文件锁。

## 打开前端

在自己的电脑建立 SSH 隧道（保持终端运行）：

```powershell
ssh -N -L 18765:127.0.0.1:8765 rmp@101.132.97.146
```

打开 <http://127.0.0.1:18765>。2026-10-19 按当前要求临时关闭访问令牌校验，整页刷新后即可查看；服务仍只监听回环地址，通过 SSH 隧道访问。鉴权代码和令牌文件保留。

恢复校验时，在 systemd 单元的 `ExecStart` 末尾加回 `--token-file /data/rmp/research-data-center/var/access-token`，执行 `sudo systemctl daemon-reload` 和 `sudo systemctl restart research-data-center`。恢复后首次登录需要令牌，管理员在服务器读取：

```sh
cat /data/rmp/research-data-center/var/access-token
```

访问令牌与 SSH 密码不同。启用时是单一管理员访问令牌；不能当作按人授权的多租户系统。团队成员按角色共享元数据、内容申请和上传留到第二阶段。服务固定回环地址，不对公网开放。

## 当前能力

- [整理规范与增补流程](docs/standards.html)：成员面对的目录、命名、版本、提交规则及公开参考依据；内部字段约定与可下载模板。当前规范版本为 v1，增补接收与自动发布尚未启用。
- [现有资源清册](docs/resource-inventory.html)：逐项映射既有入口、持久登记 ID、物理位置、说明证据、关系候选和待补项；每条提供 HTML / Markdown 说明卡。仅在管理中心保存说明，不向原数据目录写入文件。
- 前端资料导航按资料组浏览，提供资源卡、路径映射和待补说明视图；仍可使用原台账搜索、筛选和分页。
- 总览和服务器/类型/核验状态统计；关键词搜索、筛选、分页。
- 资源详情含公共路径、来源、台账字段、历史数量口径及本次路径核验。公共区是服务器存储范围，不代表开源许可、可对外分发或每个成员都有读取权限。
- JSON / CSV 元数据导出，OpenAPI 描述，供 agent 使用的语义说明与命令行客户端。
- `verified` 是路径存在且 rmp 可读取入口；`restricted` 是普通权限不可读；`documented` 是历史文档记载；`missing` 是本次核验未找到；`partial` 是不完整入口。
- `null` 是未知，0 是有来源的零值。目录重叠，不提供误导性的“全库容量求和”。

上传、原始文件下载、通用批量迁移服务、真正不可变版本、用户 RBAC、任务队列和 MCP 服务尚未实现；本次迁移由专用管理员事务执行，没有创建规划中的 `/data/share/incoming` 或增补定期 Agent 任务。当前执行规范以 [规范中心](docs/standards.html) 和 [共享盘团队规范](docs/cpfs-team-guide.html) 为准，早期 [建设计划](docs/plan.html) 和 [架构意见](docs/council-architecture.md) 保留作背景参考。

本次交付的实际检查结果见 [验收记录](docs/acceptance.md)。初始目录为 228 条资源入口；包含集合与派生物，不是 228 个独立数据集。

## Agent 使用

服务器上：

```sh
cd /data/rmp/research-data-center
/data/services/miniforge3/bin/python tools/agent_client.py --token-file var/access-token summary
/data/services/miniforge3/bin/python tools/agent_client.py --token-file var/access-token search --query DementiaBank --kind dataset
/data/services/miniforge3/bin/python tools/agent_client.py --token-file var/access-token search --kind model --query Qwen
/data/services/miniforge3/bin/python tools/agent_client.py --token-file var/access-token show <asset-id>
```

核心接口为 `GET /api/assets`、`GET /api/assets/{id}`、`GET /api/summary`、`GET /api/agent/manifest`、`GET /api/openapi.json`。启用鉴权时 API 使用 `Authorization: Bearer <token>`，浏览器使用登录会话；当前临时关闭时可省略示例中的 `--token-file` 和请求认证头。客户端支持 `--base-url` 指向本机 SSH 转发端口。API 不执行资产内容，也不返回原始数据文件。

新增 `GET /api/resource-mapping`、`GET /api/resource-mapping.csv`、`GET /api/resource-mapping/{registry_id}`，将原 `asset_id` 关联到持久登记身份、说明卡、核验范围和待办。CLI 对应 `mapping` 和 `entry <registry_id>`。这些登记身份尚不是确认后的逻辑资源或冻结版本；关系候选不能作为已核实的来源链。

`GET /api/research-guide` 提供六类研究导览、精确条目成员、新人路径与术语。映射中的 `documentation.research` 提供背景、研究用途、入门步骤、模态、语言、来源与说明证据；`confidence` 区分具体上游匹配、家族背景与本地证据，不是数据质量评分。首页按研究方向、存放组与关键词交集筛选。

Agent 应先读 scope 与 manifest，再搜索；保留资产 ID、来源快照、路径状态与使用条件，不能把文件数写成人数，不能由目录名称断言原件完整或许可证允许。

## 本地开发与验证

Python 3.10+（当前开发用 3.11，服务器用 3.14）。

```sh
python tools/build_catalog.py
python tools/build_inventory.py
python tools/build_research_guide.py
python catalog.py import --input data/catalog.json --db var/catalog.sqlite3
python -m unittest discover -s tests -v
python server.py --db var/catalog.sqlite3 --host 127.0.0.1 --port 8765
```

不传 token 参数会启用无鉴权模式；当前部署按要求临时采用此模式。恢复访问令牌校验时加回 `--token-file var/access-token`。所有数据 API 为只读，CLI 导入使用事务替换快照；重复 ID 或非法记录会使整次导入失败。

## 目录更新与备份

来源及限制详见 [docs/provenance.md](docs/provenance.md)。发布包 `data/sources` 只包含筛选后的公共区 CSV 与本次公共区轻量核验回执；原始混合台账和证据 ZIP 不随服务发布。`tools/build_catalog.py` 是规范化入口。`data/catalog.json` 是导入文档；SQLite 为运行时查询真源。HTTP 不编辑数据，因此当前可审阅重建并整体导入，不存在双向编辑冲突。

采集器只允许这两个公共根及其内部解析路径。数据目录发现最多 3 层，模型识别最多 5 层，单目录最多 10,000 个入口，总预算 20,000 个目录 / 120 秒；采用低优先级运行，不读取数据记录、不加载权重、不全盘计算容量或哈希。深层内容由父集合入口覆盖，不能把目录覆盖当作逐文件完整核验。限制与错误保留在回执中。更新采集由管理员按需执行，不在网页请求或后台周期任务中自动触发。

`tools/build_inventory.py` 只读本地公共元数据快照，生成 `data/resource-mapping.json` / `.csv`、清册和逐条说明卡。`data/resource-registry.json` 保存登记身份，必须与目录数据库一起备份；重建时保留它，避免重新分配身份。原 `asset_id` 若因上游整理发生变化，需要显式迁移绑定，不能凭相同路径自动合并。现有说明卡是带证据的过渡索引，尚未向原目录布置未来正式发布版的 README / manifest。

外部规范和内部说明模板见 `docs/standards.html` 与 `docs/templates/`。当前资料观察时间仍以原台账和公共区回执为准；清册生成时间只是说明系统构建时间。文件系统所有者不等于资料维护人，存在性、账户访问性和完整性分别记录。

逐条研究说明保存在 `data/annotations/*.json`，按原 `asset_id` 绑定，由 `tools/research_annotations.py` 校验并在清册构建时合入。补充说明时保留来源链接、审阅日期与证据；不要修改原始目录快照来伪造新的观测。`tools/build_research_guide.py` 根据清册生成六类导览及计数；出现新的存放分组时要求先审阅分类。模板在线阅读入口为 `docs/templates/index.html`，仍可下载原 Markdown 与 Schema。

更新前使用 SQLite backup API 保存快照：

```sh
/data/services/miniforge3/bin/python -c "import sqlite3; a=sqlite3.connect('file:/data/rmp/research-data-center/var/catalog.sqlite3?mode=ro',uri=True); b=sqlite3.connect('/data/rmp/research-data-center/var/catalog.before-update.sqlite3'); a.backup(b); b.close(); a.close()"
```

再运行构建与导入。该示例是同盘回滚副本，不是异地灾备；异地元数据备份、保留期与恢复演练见建设计划。不要用重扫全盘替代来源核对，也不要自动改变源目录权限。

## 服务运维

```sh
sudo systemctl status research-data-center
sudo journalctl -u research-data-center -n 50 --no-pager
sudo systemctl restart research-data-center
sudo systemctl stop research-data-center
```

新建的 systemd 单元以 rmp 身份运行，自动开机启动与故障重启，限制 CPU/内存；令牌 0600，项目根 0700。没有改动现有训练服务。轮换访问令牌后重启服务，旧会话失效。停止或移除这个新服务不会移动或删除任何已有科研数据。

`tools/remote_session.py` 仅是此次开发使用的交互 SSH 传输辅助，不是服务依赖；不存密码。密码与访问令牌不进入源码或导出目录。
