---
schema_version: '1.0'
record_type: research_run
status: draft
run_id: null
project: null
owner:
  name: null
  contact: null
started_at: null
finished_at: null
inputs:
  - resource_id: null
    version: null
    manifest_sha256: null
    upstream_revision: null
    resolved_path: null
    verification: unknown
split:
  definition_path: null
  manifest_sha256: null
  independent_unit: null
  leakage_check: pending
code:
  repository: null
  commit: null
  dirty_patch_path: null
environment:
  specification_path: null
  container_digest: null
  cuda_version: null
  gpu_description: null
execution:
  command_path: null
  config_path: null
  seeds: []
  nodes: []
outputs:
  root_path: null
  selected_checkpoint: null
  metrics_path: null
  completion_evidence: null
retention:
  policy: null
  review_after: null
  backup_reference: null
---

# 实验说明与复现记录

这是填写模板，不代表实验已运行、输入已冻结或产物已备份。未知值保持 null/unknown，状态按真实结果更新。实验路径使用已有 `/data/share/public/<username>/projects/<project>/runs/<run-id>/`；先确认所属工作区权限与配额，不创建或改变他人目录。完整规则见 [CPFS 团队规范](../cpfs-team-guide.html)。

## 研究问题与结果

写清假设、任务、主要比较、评估指标、结论及其适用范围。说明结果是探索性还是最终验证，不以测试集反复选择实验。

## 输入资料与固定版本

为每项输入记录稳定资源 ID、固定版本、清单摘要及实际读取位置。现有未冻结资料如实标明 legacy/observed，并记录观测时间、文件选择及已知变化风险；不得用 main/latest 代替版本。节点本地缓存记录对应的正式源与核验方式，不把缓存路径当资源身份。

## 划分与泄漏检查

说明独立单位为何是说话人、患者、家庭、会话或其他单位；记录 train/validation/test 的生成规则与摘要。检查同源镜像、重复内容、相邻切片、增强样本和派生特征是否跨集合。注明哪些步骤仅在训练部分拟合，测试集何时使用。

## 代码、环境与启动

记录代码提交、未提交修改补丁、完整配置、启动命令、依赖锁定/容器摘要、CUDA 与 GPU 情况、随机种子及分布式设置。不要在说明中保存 token、密码或个人敏感信息。启动前检查共享挂载、输入完整性和可用容量；避免各 rank 自动下载。

## 输出与恢复

列出 metrics、日志、checkpoint 和 artifacts。日志按 host/rank 分开；注明可恢复 checkpoint 的完整性证据，不能把临时文件视为有效恢复点。记录最佳模型选择规则、最终评估与失败尝试，不只保留最优数字。

## 派生与发布

若产生可复用数据或模型，写清父资源版本、处理参数、样本映射及本 run。晋升正式库走增补与发布流程，不直接复制进正式版本目录或覆盖输入。

## 容量、保留与备份

写明本次预计和实际占用、哪些文件可重建、哪些必须保留、责任人及复查日期。只有备份任务记录与恢复验证存在时才填写“已备份”；正式输入与唯一科研结果不作为临时缓存回收。
