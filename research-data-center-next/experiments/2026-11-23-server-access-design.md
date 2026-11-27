# 服务器账号与文件权限核对 · 2026-11-23

本记录覆盖 47 和 101。**对外可读**指工作区允许 `ml-readers` 之外的本机账号和以这些账号运行的进程读取。访问者仍通过现有的 SSH、服务器进程或已授权的挂载访问。网页的飞书登录与 Linux 文件权限分别管理。

## 成员账户

两台机器的 19 个成员账户 UID、主组 GID 和补充组集合一致。每个成员的主组与账号同名，主组 GID 等于 UID。所有成员同时属于 `ml-readers`，额外组如下表。用 `sudo -l -U` 核实了表中的管理员权限。

| UID／主组 GID | 账户及同名主组 | `ml-readers` 之外的补充组 | sudo |
| ---: | --- | --- | --- |
| 1000 | `yanzicheng` | `wheel` | 全部命令 |
| 1001 | `liusizhe` | — | 无 |
| 1002 | `jinchicheng` | — | 无 |
| 1003 | `wanhongbo` | `wheel`、`ww-data-share` | 全部命令 |
| 1004 | `liyuanchao` | — | 无 |
| 1005 | `dengjixuan` | — | 无 |
| 1006 | `luzijian` | `wheel` | 全部命令 |
| 1007 | `zhangyin` | — | 无 |
| 1008 | `hefeng` | — | 无 |
| 1009 | `lijiale` | — | 无 |
| 1010 | `luyonghua` | — | 无 |
| 1011 | `rmp` | `wheel` | 全部命令 |
| 1012 | `yuanxinchen` | — | 无 |
| 1013 | `guorui` | — | 无 |
| 1014 | `hejingheng` | — | 无 |
| 1015 | `bailu` | — | 无 |
| 1016 | `rongxiaobin` | — | 无 |
| 1017 | `wanggaogao` | — | 无 |
| 1018 | `tuyuhang` | — | 无 |

## 服务与系统账户

47 共 46 个账户、67 个组。101 共 50 个账户、71 个组。以下按实机 `getent`/NSS 枚举结果记录。

| 范围 | 账户（UID） | 用途或配置 |
| --- | --- | --- |
| 两机 | `root` (0) | 系统超级用户，主组 `root` (0) |
| 两机 | `bin` (1)、`daemon` (2)、`adm` (3)、`lp` (4)、`sync` (5)、`shutdown` (6)、`halt` (7)、`mail` (8)、`operator` (11)、`games` (12)、`ftp` (14)、`mysql` (27)、`nscd` (28) | 系统及软件保留账户 |
| 两机 | `rpcuser` (29)、`rpc` (32)、`tss` (59)、`tcpdump` (72)、`sshd` (74)、`dbus` (81)、`postfix` (89)、`systemd-resolve` (193)、`chrony` (996)、`unbound` (997)、`polkitd` (998)、`systemd-coredump` (999)、`nobody` (65534) | 系统服务和低权限运行身份，配置的 shell 为 `/sbin/nologin` |
| 仅 101 | `qemu` (107)、`research-auth` (993)、`gluster` (994)、`nginx` (995) | `research-auth` 实际运行平台认证服务。目录、科研进度网页和平台代理服务配置为 `rmp` 运行。 |

`sync`、`shutdown`、`halt` 的 shell 分别指向相应的系统命令。账户存在、配置的 shell、SSH 授权和活跃进程是不同字段，本次清单记录账户及配置，不推断各账户可否远程登录。

## 用户组及权限角色

| 组 | GID | 作用及成员 |
| --- | ---: | --- |
| `root` | 0 | 系统管理和部分系统文件的属组 |
| `wheel` | 10 | `yanzicheng`、`luzijian`、`rmp`、`wanhongbo`，两机均实测配置有全命令 sudo |
| `ml-readers` | 992 | 表中 19 个成员。用于工作区命名 ACL，也作为共享成员入口的属组。组外访问通过 `other` 条目获得。 |
| 同名主组 | 1000–1018 | 每个成员各有一个主组，用于标识文件归属 |
| `ww-data-share` | 22000 | `wanhongbo`。用于两机各自的本地 `/data/shared`，与共享 NFS `/data/share` 是不同目录。 |

两机共有的 44 个系统组如下，括号为 GID。

- `bin` (1)、`daemon` (2)、`sys` (3)、`adm` (4)、`tty` (5)、`disk` (6)、`lp` (7)、`mem` (8)、`kmem` (9)、`cdrom` (11)、`mail` (12，补充成员 `postfix`)
- `man` (15)、`dialout` (18)、`floppy` (19)、`games` (20)、`utmp` (22)、`mysql` (27)、`nscd` (28)、`rpcuser` (29)、`rpc` (32)、`tape` (33)、`utempter` (35)
- `kvm` (36，101 上有补充成员 `qemu`)、`video` (39)、`ftp` (50)、`lock` (54)、`tss` (59)、`audio` (63)、`tcpdump` (72)、`sshd` (74)、`dbus` (81)、`postfix` (89)、`postdrop` (90)
- `users` (100)、`systemd-journal` (190)、`systemd-resolve` (193)、`chrony` (993)、`unbound` (994)、`ssh_keys` (995)、`polkitd` (996)、`systemd-coredump` (997)、`render` (998)、`input` (999)、`nobody` (65534)

101 另有 `qemu` (107)、`research-auth` (989)、`gluster` (990)、`nginx` (991) 四个组。

## 目录权限设计

| 路径 | 存储与实测权限 | 日常规则 |
| --- | --- | --- |
| `/data/users/<用户>/` | 两机分别是本机 XFS。19 个入口在 101 显示 `0755`，47 显示 `0775` 且带 ACL。 | 成员拥有自己的工作区，普通文件对外 `r--`，目录对外 `r-x`。47 入口的组权限位是 ACL 掩码，实测所属组和 `ml-readers` 有效权限均为 `r-x`，组外也为 `r-x`。范围包括实际的项目、输出、工作树及同一工作区内其他普通目录。 |
| `/data/share/public/<用户>/`、`/data/share/incoming/<用户>/` | 两机挂载同一 NFS。已存在的 19 个 `public` 和 17 个 `incoming` 入口均为 `2755`。 | 成员拥有各自入口。`setgid` 使新项继承 `ml-readers` 属组，现有入口组内、组外均可列出和进入。两位新成员 `wanggaogao`、`tuyuhang` 已有 `public`，尚无 `incoming`。 |
| `/data/share/datasets`、`/data/share/models`、`/data/share_cold` | 根目录观测为 `0755`。 | 正式资料、模型和归档分别按实际子路径和数据授权管理。根目录模式无法代表所有后代权限。 |
| `/data/shared` | 两机本地目录，属主 `wanhongbo`，属组 `ww-data-share`，模式 `2770`。 | 根入口允许属主和属组读写、进入。`other::---`。101 上还配置了同等默认 ACL。 |
| `/home/<用户>/`、`/root` | 成员家目录在 101 为 `0750`，47 为 `0700` 或 `0710`。`/root` 为 `0550`。 | 个人登录目录与科研工作区分别管理。组外在这些入口没有列目录权限。 |

文件的 `r` 允许打开、分析、复制；目录的 `r+x` 允许列出和进入。修改文件需要该文件的写权限，创建、删除、改名则受其父目录的写权限和其他文件系统规则约束。组外未新增写权限。ACL 依次考虑属主、匹配的命名用户或组、`other`。命名用户和组还受 `mask` 限制，因此实测账户比仅看数字模式更可靠。

## 新文件与验证方法

- 两机成员登录 Shell 抽测的 `umask` 均为 `022`。本地 XFS 成员目录还配置默认 ACL，普通新文件和目录继承读取权。应用显式使用 `0600/0700` 或随后重设权限时，仍可产生不可互读的文件。本地修复脚本按需执行。
- NFS 共享成员区由 101 上现有 `research-share-permissions.timer` 维护，覆盖 `public`、`incoming` 和共享根下成员拥有的项目目录。每轮结束间隔 30 分钟再检查一次。最近完成的一轮改动 5 项，处理错误为 0，完成时间为 2026-11-23 23:49:23（北京时间）。
- 本地复扫复用 [ACL 修复脚本](../tools/repair_member_workspaces.py)，服务器执行版本 SHA-256 为 `644c8ddca37c991cf27aca1d5c7c6ad505932e7d7b39f900122fbc2876d3ef4b`。备份分别保存在两机的 `/var/lib/research-data-center-monitor/member-read-20261123/before-acl.jsonl.gz`。脚本按设备号限制范围，软链目标按自身路径权限访问。

## 现场验证结果

每机用 19 位成员分别创建普通目录及测试文件，再以其余成员和组外账号 `nobody` 实际读取、检查无写权限并清理临时文件。另抽查共享成员入口，确认 `nobody` 可进入 `public/bailu` 和 `incoming/hejingheng`，对 `/home/bailu` 和 `/data/shared` 则无读取和遍历权限。以 `nobody` 实际打开此前指定的 `/data/users/hejingheng/outputs/s1-audio-20261118/` 内的一个普通输出文件，结果通过。

| 主机 | 扫描目录 | 扫描普通文件 | 修复目录 | 修复普通文件 | 错误 | 成员交叉读取 | 组外读取 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 47 | 830,678 | 11,063,484 | 109 | 186 | 0 | 342/342 | 19/19 |
| 101 | 925,055 | 9,660,010 | 6,186 | 37,907 | 0 | 342/342 | 19/19 |
