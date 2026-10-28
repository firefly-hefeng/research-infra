---
schema_version: '1.0'
profile: draft
resource:
  id: null
  slug: null
  title: 待填写：资源名称
  kind: model
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
dataset: null
model:
  base_model: null
  framework: null
  architectures: []
  precision: null
  input_description: null
  output_description: null
  loading_reference: null
  evaluation_reference: null
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

> 管理团队专用完整资料卡。使用者只填写 incoming 协议 2.0 的最小 submission.json；不要求贡献者填写本卡。此草稿不能代替目标资源/版本授权。

# 模型说明

本模板是草稿。复制为目标资料的 README.md 后填写；增补入口与规则周期是否启用以服务回执为准；CPFS 迁移状态以独立存储证据为准，填写模板不触发路径切换或模型任务。YAML 是规范元数据唯一真源，正文描述使用方式和限制。

未来正式模型版本采用 `/data/share/models/<slug>/releases/<version>/`。locations 只填写有证据的实际位置；复制期间保留 `/data/models` 来源，核验切换后将新位置记为 primary、旧根兼容引用记为 legacy。保留稳定 ID、上游 revision 与历史观察，不因换盘声明新模型或已冻结版本。

## 1. 模型概述与用途

说明模型任务、输入、输出、适用范围及不适用场景。仅发现权重或缓存目录不能证明模型可加载或性能达到预期。

## 2. 来源与基础模型

填写官方仓库/资料责任方、上游 revision、基础模型及获取方式。微调模型记录基础版本、训练数据版本、处理代码与配置。未在团队目录登记的上游模型用可定位 target_ref 表示，不虚构内部 ID。

## 3. 文件与依赖

说明权重、config、tokenizer、词表及其他必要文件，框架、精度和依赖。保存上游内部结构和必要链接关系；不要单独搬迁缓存 snapshot 破坏对 blobs 的引用。

## 4. 如何加载与使用

给出最小加载示例和预期输入输出，但不执行未知代码或反序列化未知模型。写清设备/内存需求的来源；未测量就标记未知，不猜测 GPU 需求。

## 5. 评估与已知限制

提供实际评估任务、数据版本、指标、条件与来源。没有评估就写“未评估”；上游宣称与本机实测分开。不能把目录存在或权重文件数量当成模型质量证明。

## 6. 许可、团队使用与外部分发

模型、基础模型和训练数据的条件分别说明。团队公共区不等于允许公开下载；未知许可保持 unknown。维护人须认领，不能由文件系统 owner 自动推断。

## 7. 版本、派生关系与引用

区分上游 revision、本地版本和元数据修订。已发布权重变化新建版本；同一版本多处存储用 locations 表示，不重复创建资源。仅修改说明增加 metadata_revision。

## 8. 证据与待办

逐项记录 evidence、field_evidence 与 unknowns，注明文件观察、上游说明、维护人确认或计算结果。现有原位卡片保持 observed，不冒充 content_frozen。
