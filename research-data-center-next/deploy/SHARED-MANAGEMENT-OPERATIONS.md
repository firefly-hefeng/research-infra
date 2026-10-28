# 共享资料管理系统：部署与恢复

本文描述经过迁移门禁后的目标部署。实际是否完成，以 `/var/lib/research-data-center-upgrade-20261027/state.json`、systemd 和页面状态为准，不能从本文件推断已切换。

## 分层存放

| 内容 | 位置 | 约束 |
| --- | --- | --- |
| 已有共享资料 | `/data/share/datasets`、`/data/share/models` | 已有资源原样保留；本次增补工具不重排、删除或覆盖 |
| 个人增补入口 | `/data/share/incoming/<user>/<submission-id>` | 本机已确认账号的专属 bucket；原稿保留 |
| 接收发布版本 | 两库内的 `managed/<resource_id>/<version>` | 单协调器写入，独立副本，版本不覆盖；完整资料卡待团队维护 |
| 已验证代码缓存 | `/opt/research-data-center/releases/20261027-incoming-rules-mountfix` | 本机、root 所有；服务不从 OSS 执行代码 |
| 页面/清册工作副本 | `/var/lib/research-data-center/workspace` | 本机，由 rmp 维护；目录库是 `var/catalog.sqlite3` |
| 增补队列及锁 | `/var/lib/research-data-center/state` | 本机私有目录，队列 `ingestion.sqlite3`；禁止复制后在别机启写入 |
| 持久发行和备份 | `/data/share_cold/research-data-center/snapshots/<时间-随机ID>` | 完整 public release、两个一致 SQLite 快照、最后写入的 COMPLETE.json |
| 旧程序入口 | `/data/rmp/research-data-center` | 完成后为指向本机 workspace 的兼容软链 |
| 旧程序回退副本 | `/data/rmp/.research-data-center-before-cold-20261027` | 暂时保留约 373 MiB；不自动删除。大规模空间回收由独立热数据迁移完成 |

`share_cold` 实测是 `fuse.ossfs`，不是可依赖 POSIX 原子重命名和跨机锁的文件系统。只写新对象，逐个经同一挂载读回检查 SHA-256，最后写完成回执；不会使用 OSS 上的 `latest` 原子指针。读回证明当前挂载客户端可读，不单独证明服务端持久提交。每个 SQLite 快照各自一致；发行包和两数据库不是跨三者同一事务时刻的快照。接收队列可通过不可变发布回执对账。

发行包只含审阅过的公开源文件、规范、清册、模板和公共迁移回执；原 `var` 的密钥、原始进程检查及逐文件诊断保留在本机，不混进共享发行包。冷备份不自动清理历史快照，保留策略由管理团队制定。

## 调度与管理

唯一写协调器固定主机 `iZuf6jc6bqdgxmhcci4k3wZ`、普通 UID 1011、上述固定队列路径。本地 flock 防止同机并发；另外两台机器只作资料读者/投递者，UID/GID 未核实之前不能承诺其同名账号权限正确。

- `research-data-ingestion.timer`：约五分钟一次。每轮最多核验 4 个新/中断核验任务，发布 1 个精确批准的任务。不会自动 approve，不重试 failed/review，不解压、不执行模型、不联网下载、不删原稿。
- `research-data-cold-backup.timer`：每日 03:30 加至多 30 分钟随机延迟。重新打包当前公开工作副本，SQLite backup API 生成本机一致快照后写入冷盘。
- `research-data-center.service`：只读门户，仍绑定 `127.0.0.1:8765`；既有 `/progress/` 代理保留。访问令牌继续按用户要求关闭，不新增无身份的审批/发布 HTTP 入口。

```bash
systemctl status research-data-center.service research-data-ingestion.timer research-data-cold-backup.timer
journalctl -u research-data-ingestion.service -n 80 --no-pager
cat /var/lib/research-data-center-upgrade-20261027/state.json
cat /var/lib/research-data-center/state/cold-backup-status.json
python /opt/research-data-center/releases/20261027-incoming-rules-mountfix/tools/ingest_worker.py status
```

管理 CLI 以 rmp 运行，不能 sudo 成 root。审阅计划、摘要与权利后才执行 `approve`，详见 [Agent 协议](../docs/agent-protocol.md)。`enabled false` 停止新周期处理；停止或取消正在执行的系统服务须由管理员判断当前发布阶段，不能假设停止等于撤销文件操作。

## 一次性升级的前置条件

引导器位于 `/var/lib/research-data-center-upgrade-20261027`，root 持有发布包、脚本和校验摘要。它只等待已运行的热迁移，不启动第二份复制；最多等待 48 小时。迁移若进入 stopped_for_review，升级同时停止。

开始切换前要求：热迁移 finalizer 完成；两根均 published/switched/deleted；目标 mount、目录 inode、权限和旧根软链吻合；公共证据验证通过。此后保留最新 228 条资源 ID、切换后的路径和不可变迁移回执，不能用开发包内的旧复制阶段清册覆盖它们。

旧门户停止后在本机准备独立 workspace，导入和校验清册，建立专属 incoming/managed 空间，完成首轮检查及冷备份；新门户 HTTP 与 progress 通过后，原程序目录与预留软链用本机原子 exchange 交换，再开启两项 timer。任一步失败停止升级，尝试停新 timer/service 并恢复原门户；不逆转已完成的数据迁移，不删除新增提交或目标。

## 异常和恢复

不要清空 state.json 后重跑。先查 state、activation.log、旧程序/软链的真实 inode 和 systemd 状态。`stopped_for_review` 保留失败原因与回退错误；中断时可能已建好专属目录，需人工对照所有权和回执决定恢复阶段。

应用回退使用 `restore_application` 的固定旧 inode 检查与原子 exchange；只接受原目录或指向已知 workspace 的软链，拒绝替换其他目录。保留的旧 service 文件位于引导目录 `previous.service`。不得凭“看起来像旧目录”递归删除任何路径。

冷备恢复先选择存在 COMPLETE.json 的快照，逐一复核回执列出的长度与 SHA-256。解包到全新本机目录，执行 SQLite integrity_check、清册路径/数量核对及应用测试；密钥另行恢复。恢复队列仍限同一主机和固定状态路径，并先核对 CPFS 发布 READY 与队列记录，防止历史数据库回放造成重复发布。确认服务和只读接口后再开启 timer。没有完成回执的孤立对象不是可用备份。

参考：[阿里云 ossfs 限制](https://www.alibabacloud.com/help/en/oss/developer-reference/ossfs-overview/)、[SQLite 网络文件系统注意事项](https://www.sqlite.org/useovernet.html)。
