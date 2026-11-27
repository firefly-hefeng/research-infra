# 历史门户说明

此页保留此前做法及配置背景。日常入口见 [科研平台使用指南](README.md)。

# 科研资源与协作门户

面向组内的公共资料目录、服务器资源入口、成果进展、科研进度和研究来源导航。普通成员从使用指南开始；完整数据集/模型说明、协议清单和发布版本由管理团队维护。

## 五个日常入口

- **服务器资源**：查看服务器信息、GPU 任务与资源利用周报和月报，另见[算力使用](compute-guide.html)。
- **成果进展中心**：首页 `#research` 按“疾病/研究领域 → 研究任务 → 课题 → 证据”展开。
- **科研进度平台**：首次姓名登记、日报与周报、团队汇总与知识库；入口为 `/progress/`，日报为 `/progress/#daily`，另见[科研进度](progress-guide.html)。
- **文献管理**：在 `/papers/` 检索题录、收藏与笔记，另见[文献与来源](literature-guide.html)。
- **数据管理**：按“疾病/研究领域 → 资源角色 → 资料卡”查资料、复用输入、提交新增数据，另见[公共数据与模型](data-guide.html)。

使用指南均提供 `.md`、`.html` 和 `.txt` 版本；纯文本可直接粘贴到飞书。

## 成果进展与模型成果

成果进展中心以学术汇报结构展示研究问题、方法路线、核心效果、学术贡献、合作角色、落地效果、局限与下一步。DepAlign 是当前抑郁预测主线首选；MMPsy v3 与声音表达融合头仅按各自开发集范围展示，Daily Text Risk 仍是后续候选，通用疾病声音 Encoder 仍属研究方案/开发中。不同任务和量表的指标不得直接横向比较，PPT 中标注模拟的数据不得写入研究档案。

研究档案维护在 `data/research-portfolio.json`，只读接口为 `/api/platform/research`。更新时须同时核对指标证据、验证范围、服务器路径和代码包 SHA-256；接口在代码包缺失或摘要不符时拒绝返回成果数据。产品内测、合作计划、媒体传播和模型指标属于不同证据层级；合作机构按学术指导、伦理通过、紧密联系、实验室共建材料等真实角色展示，不推定共同开发或临床验证。

`static/research-assets/` 保存合作机构的原始 Logo 及来源/哈希清单，不重绘、不改色；白色透明 Logo 使用深色背景。`static/research-code/` 仅保存人工筛选的源码与说明压缩包，不包含模型权重、数据、预测结果或凭据。接口展示不等于公网推理服务，也不表示相关代码已整理成独立 SDK；日报与周报仍由 `/progress/` 独立应用处理。

## 统一分类与 public 整理

成果和数据共用十类疾病/研究领域；数据另按原始数据、派生数据、特征、模型、评测、代码/工件标记资源角色。分类 Agent 议会的职责、审核流程和发布约束见[工作规范](agent-council.md)，议会只提供审核建议，不自主迁移或发布。

2026-10-31 已将 MiDasheng autonomous 交付目录从 `/data/share/public/hejingheng/midasheng-autonomous-20261030/delivery` 整理至 `/data/share/models/unconfirmed/midasheng-autonomous-20261030`，原路径保留兼容软链。迁移数量、摘要、指标边界及其他项目的延期原因见 `data/public-migration.json`；开发集参与选模的结果不作为独立盲测或疾病结论。

## 使用者的增补流程

在 `/data/share/incoming/<用户名>/<提交名>/` 放入 `payload/` 和 `README.md`。README 只需名称、来源、用途、内容、使用限制；未知明确注明。全部传输完成后，在文末单独写“传输完成”，停止修改，并将路径交给管理员。

[增补指南](incoming-guide.html) · [README 模板](templates/incoming-README.md)

管理员负责检查、补充正式说明、准备后台协议清单和审核入库。文本完成标记不自动入队或发布。现有协议 2.0、规则校验与摘要绑定审批保留为管理工具，见 [管理员与 Agent 协议](agent-protocol.md)。普通 README 到协议的转录由管理员处理，不能宣称现有 worker 已自动完成这一步。

## 存储与状态

- 正式资料：`/data/share/datasets`、`/data/share/models`，旧根保留兼容软链；实际位置与核验时间见逐项映射。
- 实验输出：成员工作目录位于 `/data/users/<用户名>/`。47 和 101 两台服务器均已将这些目录及其中的普通文件设为实验室成员可进入、可列出和可读取，写权限仍只属于文件所有者和原有管理者；`private` 目录也按实验室内部约定开放读取。
- 共享成员目录：47 和 101 的 `/data/share` 是同一份 NFS 存储。`incoming/<用户名>`、`public/<用户名>` 以及共享根下由成员拥有的项目目录开放互读，保留已有写权限。两台机器的成员登录和交互 shell 默认 `umask 022`，普通新文件通常为 `644`，目录通常为 `755`（可带 setgid）。旧会话需重新登录或执行 `umask 022`。该存储不支持默认 ACL；101 上的 `research-share-permissions.timer` 以低优先级、4 路并行运行，在每轮结束 30 分钟后再次检查上述成员目录，补齐应用显式设置为 `600/700` 或保留旧权限的上传文件。修正有扫描延迟，不保证此类文件创建瞬间可读。任务不跟随软链，不进入快照或其他挂载；共享根下的集中管理 `datasets/models` 不属于此次成员目录维护范围。原权限变更记录和最近运行结果位于 `/var/lib/research-share-permissions/`。
- 管理系统工作副本：`/var/lib/research-data-center/workspace`；本机 SQLite、队列和锁位于受控本地目录。
- 持久发行与备份：`/data/share_cold/research-data-center`；运行代码使用 `/opt/research-data-center` 下已验证的本地发行。

三机设备规格见已采集的服务器快照。2026-10-28 在 47、101 检测到共享挂载，139 本次未检测到；成员 UID/GID 和资料权限仍需逐机确认，不能用同名账号推定同样权限。容量、服务和队列状态以接口及最新部署记录为准，文档不是实时监控。GPU 卡片另展示每卡 Unix 用户、脱敏任务名、PID、进程名和显存；固定探针不返回完整命令行、工作路径、环境变量或训练日志，也不会自动停止或重置任务。

### 算力历史与报表

中央定时任务 `research-compute-history.timer` 每 5 分钟读取一次已保存的服务器快照，写入私有状态目录中的 `compute-history.sqlite3`。快照超过 150 秒时跳过该次采样，失联只计状态。报表按北京时间自然周（周一开始）和自然月统计，整点后刷新本期预览，跨周期后自动归档。原始采样保留 400 天，周报和月报持续保留。

服务器资源页的「资源利用周报与月报」支持选择周期及下载 JSON。报告接口为 `/api/platform/compute-reports`，通过 `kind=week|month` 和 `start=YYYY-MM-DD` 读取指定周期。GPU 活跃采样占比以利用率达到 10% 的有效 GPU 采样计算。监控快照中的进程信息不写入历史库。

部署时将 `deploy/research-compute-history.service.in` 的 `@RELEASE@` 替换为当前发行目录，将服务和 `deploy/research-compute-history.timer` 安装到 systemd，再启用定时器。切换发行时同步更新服务中的发行目录，沿用原有状态目录。可用 `systemctl start research-compute-history.service` 立即取样。

## 管理团队资料

[规范中心](standards.html)维护完整资料卡与说明体系；[资源清册](resource-inventory.html)维护登记身份、来源证据、数量口径和实际位置。公共区位置不等于开放许可；目录入口可读不等于内容完整或模型可运行。

[来源说明](provenance.md)记录原台账、现场观察和研究说明的依据。[共享管理部署与恢复](../deploy/SHARED-MANAGEMENT-OPERATIONS.md)说明本地运行、冷备份和异常处理；早期规划与迁移前规范保留作历史设计参考。

## 只读接口与开发

资源接口包括 `/api/summary`、`/api/assets`、`/api/resource-mapping`、`/api/research-guide`，研究成果接口为 `/api/platform/research`。Agent 先读 `/api/agent/manifest`；后台增补状态见 `/api/ingestion/manifest`、`/api/ingestion/status` 和 `/api/ingestion/published`。公共资料 API 不提供原始数据/权重下载、任意 shell 或无身份发布操作；仅提供上述审核代码包。周报提交由独立的 `/progress/` 应用处理。

```sh
python -m unittest discover -s tests -v
python tools/check_docs.py
python server.py --db var/catalog.sqlite3 --host 127.0.0.1 --port 8765
```

目录重建仅处理已保存的公共元数据，不读取科研 payload。更新需保留 `data/resource-registry.json`、迁移回执、原始来源快照和研究说明证据。使用 SQLite backup API 生成一致备份，禁止把活跃 SQLite 或锁放在 NFS/OSS 上。部署与服务变更由维护人员执行，不要求普通成员操作运维命令。

不要把密码、访问令牌或私有诊断放进源码、文档或公开导出。
