---
schema_version: '1.0'
submission_id: null
title: 待填写：提交名称
kind: dataset
summary: 待填写：是什么、有什么用、主要文件格式。
contributor:
  name: 待填写：提交者姓名或团队账号
  contact: 待填写：团队内可联系渠道
source:
  reference: null
  description: 待填写：下载来源、采集/产生方式或为什么尚未明确。
  upstream_revision: null
rights:
  team_use: unknown
  external_distribution: unknown
  license_id: null
  basis: null
delivery:
  mode: transfer
  existing_path: null
  estimated_bytes: null
proposed_resource_id: null
proposed_version: null
relation_note: null
ready: false
---

# 增补提交说明（设计模板，入口尚未启用）

先填写 YAML 中 title、kind、summary、contributor、source.description、rights 与 delivery。未知值保留 null/unknown，不猜测；允许先形成待补充记录。resource ID、清单、校验、发布路径由后续流程生成，不要求成员手填。

## 资料说明

用几句话介绍是什么、用途、主要格式和重要限制。

## 来源和共享依据

写明来源 URL、资料责任方或采集/产生方式；说明团队使用依据及外部分发条件。提交者不一定是未来维护人。

## 文件与使用方式

列出主要目录和文件、估计容量、最小使用说明。服务器侧大文件将通过 CLI/SFTP/rsync 接入，网页小文件为可选设计。

## 原位登记还是新传输

- register：existing_path 填经核验的实际公共资料位置。未来 canonical 为 `/data/share/datasets` 或 `/data/share/models`；当前复制未完成时保留 `/data/datasets` 或 `/data/models` 来源，切换后旧根仅作为已核验的兼容别名。路径与迁移回执一致才可采用；只登记，不复制、不改权限、不移动。
- transfer：existing_path 设为 null；未来流程分配 `/data/share/incoming/<submission-id>/` 后再传入。该增补根尚未创建，接收接口尚未启用；现在不要按本模板创建目录或开始上传。

## 与已有资料的关系

如果知道对应旧资源或版本，填 proposed_resource_id / proposed_version / relation_note；不知道则留空。重复疑点由 Agent 提示，不自动删除原件。

## 提交完成

未来提交工具确认全部传输和写入结束后，生成 `manifest.jsonl` 及 `READY.json`；完成标记只含工具生成的 `submission_id`、`manifest_sha256`、`submitted_at`，分别绑定本次编号、清单原始字节的 SHA-256 和带时区完成时间。`ready` 仅由工具同步为 true，不由成员手改触发任务。完整 JSON 结构见 [ready.example.json](ready.example.json)，字段约束见 [ready.schema.json](ready.schema.json)。

Agent 核对标记、清单和内容稳定性后，在任务库登记接手并返回回执/状态；生成 READY.json 不等于已接手或已发布。标记不会冻结打开的文件，提交前必须停止所有写入；未来接入实现需要专属暂存的可验证隔离机制，并在发布前重新确认内容未漂移，不能只靠标记、改权限或目录重命名保证。

同一编号与清单摘要的重试返回同一任务，不重复发布；同一编号换清单视为冲突。内容改变后用新编号重新提交，关联前次任务；说明更正需显式修订记录，不静默改接手证据。详细协议见 [field-guide.md](field-guide.md)。当前只是说明模板，不存在正在执行的上传或定时整理任务。
