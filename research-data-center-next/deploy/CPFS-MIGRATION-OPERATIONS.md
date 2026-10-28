# CPFS 迁移维护与恢复手册

仅供本机维护者使用；不发布到网页。迁移标识：`cpfs-20261027`。记录日期：2026-10-27。本文不包含密码或令牌。

## 当前状态与固定范围

**本文写入时复制尚未完成，下面的 finalizer 服务尚属启动计划，不能据此认定已经运行或迁移完成。** 实际启动时间与 unit 查询结果另存私有 BASE 的 `finalizer-launch.json`，实时阶段见 `finalization-state.json`；本手册保留为封存发行版的一部分。

| 项目 | 固定值 / 当前观察 |
| --- | --- |
| 本机 | `iZuf6jc6bqdgxmhcci4k3wZ` |
| 应用目录 | `/data/rmp/research-data-center` |
| 私有证据目录（下文 BASE） | `/data/rmp/research-data-center/var/cpfs-migration-20261027` |
| 来源 | `/data/datasets`、`/data/models`，复制期间仍为本地 XFS 原目录 |
| 最终目标 | `/data/share/datasets`、`/data/share/models` |
| 私有复制暂存 | `/data/share/.rdc-migration-20261027`，root 0700 |
| 本地切换回退目录 | `/data/.rdc-rollback-20261027`，root 0700；只允许核验后的两库原目录进入此处 |
| 目标挂载 | `/data/share` → `10.0.0.202:/share`，实测 NFSv3，含 `hard,nolock,local_lock=all,sec=sys` |
| 已观察进程 | copy worker `850602`；其 rsync `852252`；verify waiter `862748` |

PID 是一次观察值，使用前须核对命令、启动时间、父子关系与状态文件，不能把 PID 存在当作同一个任务仍在运行。其他两台主机尚未登录核验；同一共享存储的挂载、UID/GID、旧根别名及实际可读性都不能由本机结果代替证明。

本次不接管 `/data/share/public/<username>`、`.snapshots/`、成员目录或其他服务。只删除日志明确记录、原 inode 核验通过的本地回退子树；域外 hardlink 保留，不能按源文件逻辑大小承诺实际释放量。旧 `/data/{datasets,models}` 在成功切换后成为指向目标根的兼容软链。

## 计划中的一次性后台续跑

| 参数 | 计划值 |
| --- | --- |
| transient unit | `rdc-cpfs-finalize-20261027.service` |
| 身份与命令 | root：`/data/services/miniforge3/bin/python /data/rmp/research-data-center/var/cpfs_finalize.py --execute` |
| 工作目录 | `/data/rmp/research-data-center` |
| 调度 | `Nice=15`；`IOSchedulingClass=best-effort`；`IOSchedulingPriority=7` |
| 重启 / 停止策略 | `Restart=no`；`KillMode=control-group` |

由系统级 systemd 承载后，运行不依赖本机 SSH 会话持续连接。transient unit 不代表已配置开机续跑；主机重启后先审阅状态，不自动重启迁移。它与展示服务 `research-data-center.service` 是两个不同的 unit。

启动前必须已经安装并封存审阅版本：`finalization-policy.json` 由 root 持有、非组/其他用户可写，pins 与发行清单实际文件匹配；确认已有 verify waiter 会接续校验。finalizer **不会另起 copy 或 verify**，等待现有校验完成（最长 48 小时），失败则停下。不要为“加快进度”再启动一个迁移进程。

正常顺序为：等待 `verify/passed` → 复核封存文件 → 核验后发布两目标根并交换旧根别名 → rmp 观察全部登记入口 → publisher `check` → 核验后清理旧副本 → rmp 再观察 → publisher `publish` → 配置转为共享路径 → 重建目录/说明/研究导航 → SQLite 备份与导入 → HTTP 验收 → `complete`。

## 日常只读查询

以下命令在目标服务器执行；本手册不代替执行记录。

```bash
sudo systemctl show rdc-cpfs-finalize-20261027.service --property=LoadState,ActiveState,SubState,Result,MainPID,ControlGroup,Nice,IOSchedulingClass,IOSchedulingPriority,Restart,KillMode
sudo systemctl status rdc-cpfs-finalize-20261027.service --no-pager
sudo journalctl -u rdc-cpfs-finalize-20261027.service -n 80 --no-pager
ps -o pid,ppid,lstart,stat,args -p 850602,852252,862748
findmnt -T /data/share -o TARGET,SOURCE,FSTYPE,OPTIONS
sudo lslocks -o PID,COMMAND,PATH
```

unit 尚未创建或已卸载时查询可能显示不存在；这既不表示未发生切换，也不证明后台进程已退出。以私有日志和实际拓扑核对。`finalization.lock` 和 `transfer-worker.lock` 都位于本机 XFS 的 BASE 下，只协调本机进程，不是 NFS 跨主机锁。

| BASE 内文件 | 用途 |
| --- | --- |
| `transfer-state.json` | copy / verify 阶段、worker PID、两根命令与日志哈希、校验绑定 |
| `finalization-state.json` | 续跑阶段、最后成功进度或 `stopped_for_review` 原因 |
| `finalization-run.log` | 各子命令与输出；详细错误优先查此文件 |
| `cutover-state.json` | 每根发布、交换、删除的持久化事务日志；恢复的关键证据 |
| `destination-entry-observations.json` | rmp 对 221 个去重入口的观察；不等同于内容完整性校验 |
| `models-copy.log`、`datasets-copy.log` | 复制日志 |
| `models-verification.log`、`datasets-verification.log` | 校验通过应为空；必须同时有对应成功回执和哈希 |
| `source-files.jsonl.gz`、`source-semantics.json`、`link-audit.json` | 固定源清点、语义与链接重定位证据；不能覆盖或重新生成来消除差异 |
| `source-*.json`、`usage-*.json` | 切换/清理前后来源变化、打开 inode 与挂载别名检查 |
| `catalog-before-activation.sqlite3` | 元数据激活前的 SQLite 备份；不是科研数据备份 |

```bash
sudo cat /data/rmp/research-data-center/var/cpfs-migration-20261027/finalization-state.json
sudo cat /data/rmp/research-data-center/var/cpfs-migration-20261027/transfer-state.json
sudo cat /data/rmp/research-data-center/var/cpfs-migration-20261027/cutover-state.json
sudo tail -n 100 /data/rmp/research-data-center/var/cpfs-migration-20261027/finalization-run.log
readlink /data/datasets
readlink /data/models
sudo stat -c '%n dev=%d inode=%i mode=%f uid=%u gid=%g' /data/share/datasets /data/share/models
```

详细报告可能包含路径和进程信息，应留在受保护的维护范围，不贴入公开页面。

## 完成判据：必须同时满足

1. `finalization-state.json` 的 `phase=complete`，且迁移标识和主机正确；不能仅凭 systemd 已退出或返回码判断。
2. `cutover-state.json` 的 `phase=cleaned`；两根分别是 `publication=published`、`switch=switched`、`cleanup=deleted`。校验回执完整，最终观察绑定清理后的日志。
3. 实际挂载仍是上述 NFS 来源；两个旧根分别是指向 `/data/share/datasets`、`/data/share/models` 的精确软链，目标 inode 与事务日志一致。由普通 rmp 执行 publisher `check` 重新验证证据：

```bash
sudo -u rmp /data/services/miniforge3/bin/python /data/rmp/research-data-center/tools/cpfs_publish_evidence.py check
sudo -u rmp /data/services/miniforge3/bin/python /data/rmp/research-data-center/tools/verify_deployment.py
```

4. **在线 API** 已激活共享路径，不能只检查磁盘上新生成的 JSON。下面只输出计数与状态，不打印令牌：

```bash
sudo -u rmp /data/services/miniforge3/bin/python - <<'PY'
import json
from pathlib import Path
from urllib.request import Request, urlopen
app = Path('/data/rmp/research-data-center')
token = (app / 'var/access-token').read_text().strip()
req = Request('http://127.0.0.1:8765/api/export.json',
              headers={'Authorization': 'Bearer ' + token})
with urlopen(req, timeout=15) as response:
    doc = json.load(response)
baseline = json.loads((app / 'data/sources/catalog-pre-migration.json').read_text())
assert {a['id'] for a in doc['assets']} == {a['id'] for a in baseline['assets']}
assert doc['migration']['state'] == 'switched' and doc['migration']['activated'] is True
roots = ('/data/share/datasets', '/data/share/models')
assert all(any(a['path'] == root or a['path'].startswith(root + '/')
               for root in roots) for a in doc['assets'])
print(json.dumps({'live_api': 'canonical', 'records': len(doc['assets']),
                  'migration': doc['migration']['state']}))
PY
```

记录 `available_before_bytes` / `available_after_bytes` 及实际查询时间；空闲空间差值可能包含同期其他写入，不是精确删除字节数。完成仅证明本机本次流程，不扩大为三台主机全部可用或全部外链有效。

## 故障与恢复边界

| 观察到的状态 | 处置边界 |
| --- | --- |
| copy / verify 失败、等待超时、封存哈希变化 | 保留来源、暂存和证据，核对具体错误与仍存活的进程。不要删除校验日志或更新 pin 来跳过未审阅变化。 |
| `prepared`、`rename_started` 或发布未完全落日志 | NFS 可能已完成 rename 却返回错误；结合 stage/target 实际 inode 判定，不能仅按错误重命名或覆盖。 |
| 部分根 `exchange_started` / `switched` | 手工核对旧根、目标、回退路径的实际类型和 inode。自动再交换可能反向切回，禁止盲目续跑。 |
| 两根 `switched`，但普通账户观察或 publisher check 失败 | 原目录应仍在私有回退目录；先修复并重新审阅证据，不绕过门槛删除。 |
| `cleaning` / `delete_started`，包括中断后部分文件已删除 | **禁止交换回退：原树可能已不完整。** 当前脚本拒绝自动继续，须核验剩余树和目标，再制定仅针对剩余明确子树的恢复操作。 |
| `cleaned`，但发布、构建、SQLite 或 HTTP 失败 | 数据删除阶段已完成。只恢复元数据生成/激活与服务，不反向交换、不从旧树推断完整副本；必要时使用 SQLite 备份恢复元数据，并明确实际数据仍在共享盘。 |

任何故障都不能通过删除 `finalization-state.json`、`cutover-state.json`、清空锁文件、改成功标记或直接重新启动 finalizer 来“修复”。先保存现场，核对真实进程和锁的持有者，再基于实际 inode 与日志形成具体恢复步骤。锁文件存在本身不等于锁仍被持有。

`systemctl stop` 此 root unit 会按计划中的 `KillMode=control-group` 停止 unit 内的 finalizer 及其子进程，可能打断交换或删除；应视为需要恢复审阅的维护操作，不能当作无影响的暂停。只杀父 PID 则不能保证子进程停止。已在 unit 创建前运行的 copy / verify waiter 通常不属于该 cgroup，不能假定停止此 unit 会停止它们，必须查询实际归属。

NFS `hard` 请求可能长时间阻塞；停止命令返回、超时或 PID 暂无输出都不是操作未完成的证据。不得因此并行启动第二个 copy、cutover 或 cleanup。安全恢复优先于自动重试。
