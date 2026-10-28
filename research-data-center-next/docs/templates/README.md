# 资料规范与增补模板包

## 普通成员

只需 [incoming-README.md](incoming-README.md)：名称、来源、用途、内容、使用限制。资料放入本人增补目录的 payload/。全部传输结束后，才在 README 末尾单独写“传输完成”，停止修改并交接路径。[填写指引](submission-README.md)解释具体步骤。未知信息明确注明，不要求成员制作 JSON 或哈希。

## 管理团队与 Agent

正式说明由团队维护：dataset-README.md、model-README.md、field-guide.md 和 resource-card.schema.json 保留身份、版本、来源、结构和复用约定。cpfs-run-README.md 是实验记录参考，不是增补必填表。

incoming-submission.example.json / incoming-submission.schema.json，以及 incoming-manifest-entry.schema.json、incoming-ready.schema.json 和对应示例，是后台受理协议 2.0。管理员检查普通 README 提交后，按账户与路径权限准备协议文件；现有 worker 只处理合法 READY，不会把 README 的完成声明直接当作已入队或发布。完整说明见门户的 agent-protocol.md。

未带 incoming 前缀的 submission/ready 1.0 示例保留作历史设计，不用于新接收。JSON/JSONL 示例均为虚构结构，不含真实 payload、凭据或发布批准。

## 正式资料与下载包

正式资料根为 /data/share/datasets 和 /data/share/models。普通成员不写入正式库，管理员审核发布并维护说明。公共位置不等于开放许可，文件属主不等于资料维护人。

standards-kit.zip 包含本目录全部 Markdown、JSON 和 JSONL 源文件，与在线下载逐字节对应；不含网页、真实数据或 ZIP 本身。网页说明请返回门户查看 incoming-guide.html、standards.html 和 templates/index.html。
