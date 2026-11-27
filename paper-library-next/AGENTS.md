# 文献模块

先读本模块 [README](README.md)。平台接入见[统一 Agent 手册](https://rmp.wuwangwo.top/docs/agent-guide.md)和[模块速查](https://rmp.wuwangwo.top/docs/agent-modules.md)。在线手册需要门户登录；生产部署不要求相邻目录存在门户源码。日常读取 `/papers/api/catalog`。管理和导出使用 `/papers/api/state`、`/papers/api/export`；门户 `/api/platform/literature` 是资料来源索引。

整理单篇或队列时读 [paper-curator](skills/paper-curator/SKILL.md)，按原文证据生成并校验卡片，保留 SHA-256、原件、笔记和收藏。题录可读不代表原文可读，受限全文沿用既有权限。

沿关系找论文时用 `GET /papers/api/graph`。每条边的 `target` 对应目录论文 ID，`fields` 给出这条关系的来源。署名按原记录匹配，独立主题与分类分开计数。字段和计数示例见[模块 README](README.md#文献委员会如何维护发现与阅读)。

扫描、整理、生成解读及修改设置均有写入作用；仅按任务范围调用。独立服务的可选共享密码与门户登录分别处理，模型配置不写进文档。自动整理与科研执行边界见[平台自动维护说明](https://rmp.wuwangwo.top/docs/agent-maintenance.md)。仓库副本的共读文档位于 `../research-data-center-next/docs/`，此相对路径不作为生产布局约定。
