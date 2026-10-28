# 科研主力库规范 1.0：字段与执行约束

适用范围：完整编目数据集和模型两类公共资料库，未来规范位置为 `/data/share/datasets` 与 `/data/share/models`。截至本次文档修订，CPFS 复制尚未完成；`/data/datasets`、`/data/models` 仍是复制期间来源，只有核验与切换回执齐全后才成为指向新根的兼容别名。来源、许可或维护人未知不排除既有公共区条目；不因迁移新增扫描成员工作区，也不跟随越界链接采集内容。本文没有启用上传、定时 Agent 或 `/data/share/incoming`，该增补根尚未创建。共享盘权限、并发下载和实验约定见 [CPFS 团队规范](../cpfs-team-guide.html)。

## 1. 权威元数据与过渡

正式规范的唯一元数据真源是版本目录 `README.md` 的 YAML front matter；正文负责解释用途、方法、限制和使用方式。不要另行手工维护重复的 metadata.yaml 或数据库字段。SQLite、JSON、CSV 和前端为读取或导出视图；接入任务状态、日志及有时间戳的实时观察是运营记录，不得擅自覆盖 README 的维护人、许可或版本关系。

当前旧资料仍由目录快照和 sidecar 描述。这是过渡状态，不是已经迁移到 README 真源。本轮现有原位卡片均不能被称为冻结版本。采用流程应逐项保留 `legacy_ids → resource.id → 历史位置 / 经核验的当前位置` 映射。先在项目侧核对卡片，不因填写模板擅自改动原目录。已授权的 CPFS 迁移单独执行清点、复制、校验、切换与回收；模板和路径示例不构成完成回执，也不自动提升内容保证状态。

当一个资源正式切换到 README 模式后，停止从旧 CSV 或 sidecar 回写规范字段，保留它们为历史证据。新的真实文件观察可以按自己的时间和范围展示，不能静默把“源文档宣称”升级为“本机已测”。

## 2. 三种配置档与两道校验

| profile | 用途 | 身份与状态要求 |
| --- | --- | --- |
| draft | 可填写模板和待补充卡片 | 允许 null/unknown 和未分配 ID；不是已发布资料 |
| legacy | 已存在公共区资料的原位说明 | resource.id 必须存在；release.state 固定 observed；不要求改变现有目录 |
| release | 正式发布版本的完整卡片 | 需要 ID、slug、版本、实际认领的维护人、来源、团队使用依据、位置与全覆盖清单；状态为 manifest_pinned 或 content_frozen |

Schema 只验证字段、类型、枚举和部分条件；不会证明权利真实、文件可读、字节完整、路径没有越界或内容已经不可变。运行时仍须验证路径边界、证据引用、清单与实际文件、内容写入约束、授权和容量。

发布阶段满足已批准规则的新版本可以自动入库，不逐次要求人工审批。自动处理条件包括：身份有效、责任人与来源清楚、团队使用有依据、不覆盖旧版本、清单与内容匹配、容量充足、无冲突、任务处于预定低影响预算。外部分发仍独立判定，未知不得放行。许可冲突、疑似重复、来源不明的新传输、语义不清或大任务进入待处理，不自动搬库、删副本、转换格式或训练。

## 3. 严格字段定义

所有 schema 为 JSON Schema Draft 2020-12。YAML 用安全解析器转换为 JSON 兼容对象后校验；拒绝自定义标签、重复键、非有限数值。日期统一使用带时区的 ISO 8601 字符串，建议写成带引号的 YAML 字符串。没有资料填 null，未知枚举填 unknown；空字符串不能代替未知。空列表表示尚未记录任何项目，不证明实际没有。

| 字段组 | 类型与必备子字段 | 语义 |
| --- | --- | --- |
| schema_version | 字符串，固定 `1.0` | 卡片结构版本，不是数据版本 |
| profile | draft / legacy / release | 元数据完整度与用途，不是传输状态 |
| resource | id、slug、title、kind、summary、tasks、tags、legacy_ids | 稳定资源身份；kind 为 dataset/model/collection/feature/annotation/artifact。路径集合不能因位于 models 根就标作可用模型 |
| release | version、upstream_revision、origin、state、metadata_revision、updated_at | 本地内容版本、上游 revision、原始/派生性质与元数据修订分别管理 |
| maintainer | id、display_name、contact | 实际认领维护责任的人或团队；不能从 Unix owner 推断 |
| sources[] | kind、reference、revision、acquired_at、evidence_refs | 来源分为上游仓库、出版物、成员贡献、历史台账或 unknown；reference 可以是 URL、文档定位或资料责任方依据 |
| rights | metadata_visibility、team_use、external_distribution、license_id、license_reference、evidence_refs | 元数据可见、团队使用、外部分发三项分开。license_id 优先实际 SPDX 标识，自定义条款需给定位，不编造许可证 |
| locations[] | host_id、path、role、access、checked_at、evidence_refs | 实际位置与时间化访问观察。role=primary/replica/legacy；access=readable/restricted/missing/unknown。新 canonical 使用 `/data/share/datasets`、`/data/share/models`；旧两根保留复制期间来源或 legacy 兼容记录，运行时继续按回执核对位置与链接边界 |
| relations[] | kind、target_id、target_ref、version、evidence_refs | 至少提供 target_id 或 target_ref。kind=derived_from/fine_tuned_from/variant_of/supersedes/uses_dataset；内部资源引用尽量固定版本，上游引用提供 revision |
| dataset | sample_unit、sample_count、languages、modalities、splits、data_dictionary_ref、collection_method | dataset 类型必填此对象，model 设 null；样本单位不等同文件数、人数或路径数 |
| model | base_model、framework、architectures、precision、input_description、output_description、loading_reference、evaluation_reference | model 类型必填此对象，dataset 设 null；未加载、未评估就写未知，不能由目录推断性能或硬件要求 |
| manifest | path、manifest_sha256、content_coverage、file_count、total_bytes、checked_at | path 相对版本目录；摘要针对 manifest 文件字节，不是对整个库的笼统完整性宣称 |
| evidence[] | id、kind、reference、observed_at、producer、method、scope | 可核对的依据；不存密码、令牌或不必要的个人内容 |
| field_evidence | JSON Pointer → 证据 ID 数组 | 如 `/sources` 或 `/dataset/sample_count`；引用须实际存在于 evidence，不可悬空 |
| unknowns[] | field、reason、next_action | 缺失与冲突显式记录；不要求 Agent 猜测补全 |

`rights.metadata_visibility` 为 team/restricted/unknown；`team_use` 为 allowed/restricted/unknown；`external_distribution` 为 allowed/conditional/prohibited/unknown。已有公共区资料即使全是 unknown 也应保留原位记录；新内容自动发布要求团队使用依据明确，不代表允许外部分发。

`release.origin` 为 original/derived/mixed/unknown；`state` 为 observed/manifest_pinned/content_frozen。`metadata_revision` 是正整数。仅修正说明时增加元数据修订，不伪造新的内容版本；标签、权重、文件或正式 split 改变时新建内容版本。

新正式版本的目标布局为 `/data/share/{datasets,models}/<slug>/releases/<version>/{README.md,manifest.jsonl,content/}`。规划中的路径不能提前填成已存在的 primary 位置；实际切换后才将核验过的新位置记为 primary，旧路径可保留为 legacy 并关联兼容别名证据。`locations.role` 的 primary/replica/legacy 枚举与其他字段契约保持不变；legacy 字段本身不证明路径已经是软链。

资源 ID 由登记流程分配并长期保留，不依赖路径、slug 或内容哈希；示例 `rdc-...` 只是命名约定。旧 asset ID 作为 legacy_ids 保存，不在未知情况下把多个同名条目强行合为一个资源。slug 仅用小写字母、数字和连字符；版本可用 v001 或明确上游 revision 的安全短名，真实上游 revision 另存。

## 4. 证据类型与冲突处理

| kind | 能支持的陈述 | 不能支持的陈述 |
| --- | --- | --- |
| source_document | 文档在某时刻作出某声明 | 当前路径可读、当前内容未变 |
| upstream_metadata | 仓库配置、模型卡、数据卡中的声明 | 本地实测性能、实际硬件需求 |
| filesystem_observation | 本次路径、大小、文件类型、账户可读性 | 内容完整、许可授权、维护责任 |
| maintainer_statement | 具体维护人对归属、用途或许可依据的确认 | 不相关第三方权利已经获批 |
| computed_checksum | 给定文件/范围在某时刻的内容摘要 | 范围之外内容完整、逻辑数据相同 |
| processing_record | 输入、代码、参数、输出之间的处理关系 | 未记录的数据处理或因果保证 |

同一字段的两个依据矛盾时并列保留证据，unknowns 记录冲突，停止自动发布受影响的新内容。不要只按“较新”或“来自文件名”就覆盖高质量来源。Agent 自动生成的解释应注明其使用的证据，不构成独立事实证据。

## 5. 资源、版本、内容表示和多副本

- 同一资源有多个版本；同一版本可以有多个位置。复制到另一目录不会产生新资源。
- 同名不证明相同，内容摘要相同只证明被核验字节相同，不自动授权跨权限去重或删除。
- 原始封装、解压表示和格式转换分别说明。转换后的内容以派生关系和处理记录说明，不把“看起来相同”当作同一版本。
- 同一任务的数据修订可作为新版本；独立用途、独立维护的派生数据集可分配新 ID，记录 derived_from。
- 微调模型一般单独登记并关联基础模型与训练数据；模型缓存容器和 subject 目录不自动成为独立模型或数据集。
- 普通硬链接不是冻结机制；上游目录可变时只能 observed 或 manifest_pinned。content_frozen 需要实际写入约束、确定清单和恢复安排。
- 本轮已授权的 CPFS 迁移按专用事务执行，当前复制尚未完成。稳定 ID、来源和历史证据保留；仅在切换验证后激活新位置，旧根保留兼容入口。日常 Agent 不借此获得批量迁移、删源或调整运行路径的通用权限。

## 6. manifest.jsonl 约定

每行一个 JSON 对象，UTF-8 编码，字段由 manifest-entry.schema.json 定义。path 相对 content/，不能是绝对路径或带 `..` 的条目路径；按路径排序，保证同一份清单可复核。每个规范化路径唯一。

file 条目：size_bytes 为非负整数，sha256 为内容字节摘要或未做校验时的 null，link_target=null。

directory 条目只用于需要保留的空目录，size_bytes=0，sha256=null，link_target=null。

symlink 条目：记录相对 link_target，sha256=null。link_target 可含合法的 `..`，但运行时须以链接所在目录解析，最终目标必须留在同一 content/ 边界，不能仅靠正则通过。保留既有模型缓存的内部引用需要单独核对，不能为方便打包盲目跟随链接。这是未来正式 release 清单的边界；迁移中的历史绝对外链或失效链接另记节点依赖，不自动改写、删除或把域外内容一并搬入。

`content_coverage=full` 要求列全声明 content/ 内的有效文件与必要链接，所有普通文件具备可验证 SHA-256，检查路径唯一、边界、文件数和字节数。manifest_sha256 是整个清单文件的 SHA-256；这个值单独成立不证明各数据文件均正确。

`manifest.example.jsonl` 仅描述一个虚构空文件，摘要来自空字节的标准 SHA-256；没有真实内容文件。`released-dataset.example.json` 也只是完整字段的虚构样例，不是服务器已发布、已授权或已冻结的资源。

## 7. 提交最小字段与正式完整字段

成员提交时只需名称、类型、简述、可联系的提交者、来源说明、团队使用/外部分发声明和接入模式。未知许可允许明示 unknown，进入待补充；原位编目不因此排除条目。estimated_bytes 可先未知，但新的大文件传输开始前必须给出可执行的容量预约。

正式 release 卡片补齐稳定 ID、slug、内容版本、认领维护人、来源定位、团队使用证据、实际位置、完整清单和校验范围。许可证未知不能擅自填写开放许可；若团队使用已有明确依据，可以内部发布，外部分发仍保持禁止或未知。Schema 的 release 合法性不等于自动发布策略已经通过。

## 8. 增补流程（设计，未启用）

规划目标：`/data/share/incoming/<submission-id>/{README.md,manifest.jsonl,content/,READY.json}`。该增补根尚未创建，接收接口、定时 Agent 与自动发布尚未启用；本次管理员执行的 CPFS 迁移不等于增补流程已上线。

拟定流程：draft → submitted → validating → needs_information / ready → publishing → published；失败与取消单独记状态。needs_information 是条件分支，不要求每次发布人工确认。提交模板的 `ready` 布尔值仅为提交完成状态的展示字段，由工具维护；它不同于任务通过验证后的 ready 状态，也不能独自触发接手或发布。

### 8.1 完成标记：READY.json

transfer 模式由提交工具确认传输结束、关闭写入文件，生成最终 `manifest.jsonl`，计算清单文件原始字节的 SHA-256，再写入临时标记并原子重命名为 `READY.json`。三个字段全部由工具生成，成员不用手填：

```json
{
  "submission_id": "example-submission-001",
  "manifest_sha256": "6b098dfc1628d033b660da0b22b2d0002a34c90d03bd56fc3a490b60ddc5230c",
  "submitted_at": "2026-10-19T00:00:00+08:00"
}
```

以上是虚构结构示例，与本包 `manifest.example.jsonl` 的实际字节摘要对应，不是已提交任务。正式 `manifest_sha256` 必须重新计算；换行或其他字节改变也会使摘要不同。`submission_id` 必须与分配的编号和暂存目录匹配；`submitted_at` 是带时区的首次完成时间，重试保留原标记。字段约束见 `ready.schema.json`，实际文件名一律为 `READY.json`。

### 8.2 接手确认与内容稳定性

Agent 先验证标记结构、身份和清单摘要，再以 `(submission_id, manifest_sha256)` 在任务库中原子登记接手，返回同一任务的回执/状态；只有回执确认接手后，提交端才显示已接手。接手记录同时保存提交说明的摘要与校验范围。完成标记不是 Agent 的接手回执，也不是许可或完整性证明。

`READY.json` 不能冻结仍然打开的文件。上传者必须结束所有写入；后续实现还须为专属暂存采用可验证的停止写入和隔离/稳定快照机制，再读取内容。仅改权限、重命名目录或生成标记不能阻止已打开文件描述符继续写入。无法确保稳定时不得宣称已冻结或自动发布；原位 register 不因完成标记变为冻结版本，也不改变原文件权限。

接手后仍要按清单核对实际文件集合、字节数与内容摘要，并在发布前确认没有漂移；清单摘要匹配仅说明清单未变。发现文件仍在增长、清单变化或内容摘要不符时，停止处理，记录冲突并退回待补充，不发布不稳定内容。

### 8.3 重试与幂等

同一 `submission_id` 和清单摘要的重复提交/重试，必须返回既有任务及状态，不能重复分配资源、复制内容或发布版本；`submitted_at` 不作为制造新任务的依据。同一编号携带不同清单摘要视为冲突，不覆盖原任务或原标记。内容改变后使用新提交编号重新生成清单与标记，并关联前次任务；说明更正必须进入同一任务的显式修订记录或新提交，不能静默覆盖接手证据。发布阶段另以目标资源 ID 与版本的唯一约束防止不同任务覆盖同一版本，失败重试从持久化状态恢复。

register 模式只登记经核验的公共资料位置：复制期间仍可记录 `/data/datasets`、`/data/models` 来源；切换后优先记录 `/data/share/datasets`、`/data/share/models`，旧根仅作为已验证的兼容别名。Schema 接受旧/新根不证明路径已切换或可读，运行时仍需与迁移回执一致。未查明内容时保留 observed。transfer 模式未来通过 CLI/SFTP/rsync 进入 `/data/share/incoming/<submission-id>` 专属暂存，网页小文件可选。两者共用说明模板、任务状态和处理规则，不做两套互相冲突的入口。

符合已批准规则的新版本可自动发布；大批迁移、删除、去重、格式转换、特征重算、训练、授权冲突或来源语义不清均另行处理。原位来源不因任务取消而被删除。需要自动化的具体周期和运行预算由后续实施确认，本次没有创建增补自动化。共享挂载含 nolock/local_lock=all，不能用 flock 或 HF 缓存锁充当全组下载锁；未来接单与发布由单一协调入口裁决，活跃 SQLite 保留本机。详见 [CPFS 下载与发布规则](../cpfs-team-guide.html#downloads)。

## 9. 外部依据如何采用

以下是原则适配，不声称复制机构内部架构或已取得 FAIR 认证。

| 官方来源 | 采用的原则 | 本地规则 |
| --- | --- | --- |
| MIT 文件组织 | 提前约定目录和命名，并用共享投递结构与 README 帮助贡献者采用 | 两内容根、版本目录、一个增补区和一套填写模板 |
| MIT 文档与元数据 | 记录身份、来源、处理、权利和方法 | 明确 resource/maintainer/sources/rights/relations，未知不推断 |
| Google Data Cards | 说明数据形成、用途和演变 | 数据模板包括采集、处理、字段、适用任务和限制 |
| Google Model Cards | 说明模型用途、限制和评估条件 | 模型模板区分上游说明、本机加载和实际评估 |
| Hugging Face Cards | README 中结合机器元数据与人类说明 | YAML + Markdown 单卡，数据库作为索引；不是声称本地 schema 与 HF 字段完全兼容 |
| FAIR | 稳定标识、可检索元数据、来源与使用条件；访问可有认证 | 稳定资源 ID、可读卡片与 API、明确许可和元数据范围；FAIR 不等于无条件公网开放 |

官方链接：

- [MIT Organize your files](https://libraries.mit.edu/data-management/store/organize/)
- [MIT Documentation & metadata](https://libraries.mit.edu/data-management/store/documentation/)
- [Google Data Cards](https://research.google/pubs/data-cards-purposeful-and-transparent-dataset-documentation-for-responsible-ai/)
- [Google Model Cards](https://research.google/pubs/model-cards-for-model-reporting/)
- [Hugging Face Dataset Cards](https://huggingface.co/docs/hub/main/datasets-cards)
- [Hugging Face Model Cards](https://huggingface.co/docs/hub/main/model-cards)
- [FAIR Guiding Principles](https://www.gofair.foundation/fair-principles)
- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)