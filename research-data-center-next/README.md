# 科研资源与协作门户

面向组内的公共资料目录、服务器资源入口、科研进度和研究来源导航。普通成员从四份指南开始；完整数据集/模型说明、协议清单和发布版本由管理团队维护。

## 四个日常入口

- [算力使用](docs/compute-guide.html)：查看服务器信息、选择资源、共享计算约定。
- [科研进度](docs/progress-guide.html)：首次姓名登记、日报与周报、团队汇总与知识库；平台入口为 `/progress/`，日报为 `/progress/#daily`。
- [文献与来源](docs/literature-guide.html)：在 `/papers/` 检索题录、收藏与笔记，另从资源参考查数据集、模型的官方说明。
- [公共数据与模型](docs/data-guide.html)：查资料、复用输入、提交新增数据。

四份指南均提供 `.md`、`.html` 和 `.txt` 版本；纯文本可直接粘贴到飞书。

## 研究进展与模型成果

首页 `#research` 以学术汇报结构展示研究问题、方法路线、核心效果、学术贡献、合作角色、落地效果、局限与下一步。DepAlign 是当前抑郁预测主线首选；MMPsy v3 与声音表达融合头仅按各自开发集范围展示，Daily Text Risk 仍是后续候选，通用疾病声音 Encoder 仍属研究方案/开发中。不同任务和量表的指标不得直接横向比较，PPT 中标注模拟的数据不得写入研究档案。

研究档案维护在 `data/research-portfolio.json`，只读接口为 `/api/platform/research`。更新时须同时核对指标证据、验证范围、服务器路径和代码包 SHA-256；接口在代码包缺失或摘要不符时拒绝返回成果数据。产品内测、合作计划、媒体传播和模型指标属于不同证据层级；合作机构按学术指导、伦理通过、紧密联系、实验室共建材料等真实角色展示，不推定共同开发或临床验证。

`static/research-assets/` 保存合作机构的原始 Logo 及来源/哈希清单，不重绘、不改色；白色透明 Logo 使用深色背景。`static/research-code/` 仅保存人工筛选的源码与说明压缩包，不包含模型权重、数据、预测结果或凭据。接口展示不等于公网推理服务，也不表示相关代码已整理成独立 SDK；日报与周报仍由 `/progress/` 独立应用处理。

## 使用者的增补流程

在 `/data/share/incoming/<用户名>/<提交名>/` 放入 `payload/` 和 `README.md`。README 只需名称、来源、用途、内容、使用限制；未知明确注明。全部传输完成后，在文末单独写“传输完成”，停止修改，并将路径交给管理员。

[增补指南](docs/incoming-guide.html) · [README 模板](docs/templates/incoming-README.md)

管理员负责检查、补充正式说明、准备后台协议清单和审核入库。文本完成标记不自动入队或发布。现有协议 2.0、规则校验与摘要绑定审批保留为管理工具，见 [管理员与 Agent 协议](docs/agent-protocol.md)。普通 README 到协议的转录由管理员处理，不能宣称现有 worker 已自动完成这一步。

## 存储与状态

- 正式资料：`/data/share/datasets`、`/data/share/models`，旧根保留兼容软链；实际位置与核验时间见逐项映射。
- 实验输出：成员获准使用的个人工作目录，不写回正式资料库；系统不接管其他成员的目录。
- 管理系统工作副本：`/var/lib/research-data-center/workspace`；本机 SQLite、队列和锁位于受控本地目录。
- 持久发行与备份：`/data/share_cold/research-data-center`；运行代码使用 `/opt/research-data-center` 下已验证的本地发行。

三机设备规格见已采集的服务器快照。2026-10-28 在 47、101 检测到共享挂载，139 本次未检测到；成员 UID/GID 和资料权限仍需逐机确认，不能用同名账号推定同样权限。容量、服务和队列状态以接口及最新部署记录为准，文档不是实时监控。GPU 卡片另展示每卡 Unix 用户、脱敏任务名、PID、进程名和显存；固定探针不返回完整命令行、工作路径、环境变量或训练日志，也不会自动停止或重置任务。

## 管理团队资料

[规范中心](docs/standards.html)维护完整资料卡与说明体系；[资源清册](docs/resource-inventory.html)维护登记身份、来源证据、数量口径和实际位置。公共区位置不等于开放许可；目录入口可读不等于内容完整或模型可运行。

[来源说明](docs/provenance.md)记录原台账、现场观察和研究说明的依据。[共享管理部署与恢复](deploy/SHARED-MANAGEMENT-OPERATIONS.md)说明本地运行、冷备份和异常处理；早期规划与迁移前规范保留作历史设计参考。

## 只读接口与开发

资源接口包括 `/api/summary`、`/api/assets`、`/api/resource-mapping`、`/api/research-guide`，研究成果接口为 `/api/platform/research`。Agent 先读 `/api/agent/manifest`；后台增补状态见 `/api/ingestion/manifest`、`/api/ingestion/status` 和 `/api/ingestion/published`。公共资料 API 不提供原始数据/权重下载、任意 shell 或无身份发布操作；仅提供上述审核代码包。周报提交由独立的 `/progress/` 应用处理。

```sh
python -m unittest discover -s tests -v
python tools/check_docs.py
python server.py --db var/catalog.sqlite3 --host 127.0.0.1 --port 8765
```

目录重建仅处理已保存的公共元数据，不读取科研 payload。更新需保留 `data/resource-registry.json`、迁移回执、原始来源快照和研究说明证据。使用 SQLite backup API 生成一致备份，禁止把活跃 SQLite 或锁放在 NFS/OSS 上。部署与服务变更由维护人员执行，不要求普通成员操作运维命令。

不要把密码、访问令牌或私有诊断放进源码、文档或公开导出。
