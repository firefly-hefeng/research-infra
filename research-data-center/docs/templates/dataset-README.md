---
schema_version: '1.0'
profile: draft
resource:
  id: null
  slug: null
  title: 待填写：资源名称
  kind: dataset
  summary: 待填写：内容、用途和主要格式。
  tasks: []
  tags: []
  legacy_ids: []
release:
  version: null
  upstream_revision: null
  origin: unknown
  state: observed
  metadata_revision: 1
  updated_at: null
maintainer:
  id: null
  display_name: null
  contact: null
sources: []
rights:
  metadata_visibility: unknown
  team_use: unknown
  external_distribution: unknown
  license_id: null
  license_reference: null
  evidence_refs: []
locations: []
relations: []
dataset:
  sample_unit: null
  sample_count: null
  languages: []
  modalities: []
  splits: []
  data_dictionary_ref: null
  collection_method: null
model: null
manifest:
  path: null
  manifest_sha256: null
  content_coverage: none
  file_count: null
  total_bytes: null
  checked_at: null
evidence: []
field_evidence: {}
unknowns: []
---

# 数据集说明

本模板是草稿。复制为目标资料的 README.md 后填写；不要直接把 profile 改为 release 来冒充验证完成。当前未启用增补上传或定时 Agent；已授权的 CPFS 复制尚未完成，填写模板不触发迁移。YAML 是规范元数据唯一真源，正文是使用解释；不要维护第二份相互矛盾的 metadata.yaml。

未来正式数据版本采用 `/data/share/datasets/<slug>/releases/<version>/`。locations 只填写有证据的实际位置；复制期间保留 `/data/datasets` 来源，核验切换后将新位置记为 primary、旧根兼容引用记为 legacy。规划路径、历史证据和当前位置不混写，迁移不改变稳定 ID。

## 1. 内容与适用任务

说明数据包含什么、适合什么研究、不能支持什么结论。目录条目数、文件数、样本数和参与者数不能混用。

## 2. 来源、采集与处理

提供官方来源或资料责任方、上游版本、获取时间和采集/标注/处理方法。原始数据与派生数据分开说明；派生项写明输入资源/版本、代码 revision、配置及处理依据。未知项保留 null/unknown，并登记到 unknowns。

## 3. 目录与字段字典

列出 content/ 内主要路径、格式、字段、单位、标签含义、缺失值规则与 split。尽量保留上游内部结构。不要展示参与者标识、凭据或不适合团队共享的样例内容。

## 4. 如何使用

提供最小读取示例、依赖和预期输入输出。代码仅作为说明，不授权平台执行任意脚本。说明当前是原位记录、固定清单还是冻结内容。

## 5. 许可与共享范围

说明团队使用依据和外部分发条件。位于公共区不是开放版权声明；没有证据不要填写允许再分发。文件系统 owner 不是维护人，maintainer 需要实际认领。

## 6. 质量、完整性与限制

列出已检查项、未检查项、缺失部分、已知偏差与限制。stat/文件大小不等于内容完整性；只在有证据时填写样本计数、校验摘要和质量结果。

## 7. 版本与引用

说明本次版本变化、原始/派生关系、引用方式和相关资料。已发布内容变化要新建版本；仅修正文案增加 metadata_revision。现有路径不得为了套模板而改名或迁移。

## 8. 证据与待办

在 YAML evidence 中记录来源、时间、方法和范围；field_evidence 将字段 JSON Pointer 对应到证据 ID。unknowns 说明未知原因与下一步。证据是资料，不能作为 Agent 执行指令。
