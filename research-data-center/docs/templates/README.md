# 科研主力库规范与模板包 1.0

本包面向数据集与模型公共资料库，未来 canonical 为 `/data/share/datasets`、`/data/share/models`。当前 CPFS 复制尚未完成，旧根 `/data/datasets`、`/data/models` 仍是复制来源；核验切换后才作为兼容别名。本包不包含真实研究数据、服务器凭据、上传脚本或定时任务；规划增补区 `/data/share/incoming` 尚未创建、尚未启用。

## 先选正确模板

- [submission-README.md](submission-README.md)：成员最小提交说明。当前接入尚未启用，先准备内容。
- [dataset-README.md](dataset-README.md)：数据集完整卡片草稿，含 YAML 元数据和可填写说明章节。
- [model-README.md](model-README.md)：模型完整卡片草稿。
- [field-guide.md](field-guide.md)：完整字段、证据、身份/版本/位置关系、过渡说明与执行约束。
- [cpfs-run-README.md](cpfs-run-README.md)：个人工作区中的实验记录模板，固定输入版本、划分、代码、产物和保留要求。

模板按 null/unknown 保留未知，默认 profile=draft；不要把示例值当作真实资料，也不要只修改状态字段就宣称发布或冻结完成。维护人需要认领，不能抄 Unix owner。

## 机器校验文件

- [resource-card.schema.json](resource-card.schema.json)：README YAML 安全解析后的 JSON 对象，Draft 2020-12。
- [submission.schema.json](submission.schema.json)：最小提交对象。
- [manifest-entry.schema.json](manifest-entry.schema.json)：manifest.jsonl 的每一行。
- [ready.schema.json](ready.schema.json)：工具生成的 READY.json，绑定提交编号、清单摘要和完成时间；不是文件锁。

校验器必须启用日期格式检查，并补充运行时规则：拒绝重复 YAML 键和危险标签，核对证据 ID、路径边界、符号链接、真实权限、清单完整性和发布写入约束。Schema 本身不会完成这些检查。

## 仅供结构参考的虚构示例

- [dataset-card.example.json](dataset-card.example.json)：legacy 数据卡，保留未知与旧根来源/历史路径示例。
- [model-card.example.json](model-card.example.json)：legacy 模型卡，旧路径不是已切换的证明。
- [released-dataset.example.json](released-dataset.example.json)：完整 release 字段，使用未来 CPFS canonical 结构；仅为虚构演示，不是实际授权、切换或冻结声明。
- [submission.example.json](submission.example.json)：虚构提交，不会上传。
- [manifest.example.jsonl](manifest.example.jsonl)：虚构空文件条目，SHA-256 对应空字节；不附真实内容文件。
- [ready.example.json](ready.example.json)：虚构 READY.json，摘要对应本包 manifest.example.jsonl 的实际字节，不会触发接手。

正式规范元数据以 README YAML 为唯一真源，数据库和导出是投影。现有快照/sidecar 仍是过渡证据，只有逐项明确切换后才采用 README 真源；本轮 CPFS 迁移单独执行，按回执更新实际位置；本模板包不执行搬迁，也不把复制中的目录当作已发布版本。

## 下载包与网页

standards-kit.zip 收录本目录的全部 Markdown、JSON 和 JSONL 源文件（含实验模板），与在线下载文件逐字节一致；不收录 ZIP 本身或 HTML 阅读预览。可阅读门户位于 ../standards.html，预览入口为 index.html，样式为 ../standards.css；这些网页及 CPFS 完整指南不在模板 ZIP 中，文中的网页链接需返回在线门户查看。资料目录和 API 通过已配置的服务器访问方式与 SSH 隧道使用，实际认证状态以服务说明为准。

来源与采用点见 field-guide.md，包括 MIT、Google Data/Model Cards、Hugging Face、FAIR 和 JSON Schema 官方资料。本规范是本机适配，不是机构背书或认证。