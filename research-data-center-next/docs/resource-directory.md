# 数据集与模型分类目录

2026-11-14。本地代码已接入，尚未部署服务器。

## 展示规则

数据管理页新增「按分类找数据集与模型」，支持资源类型、研究大类、细分类、接入状态及关键词筛选。每个登记资源只展示一张卡片，每页6条；分包在详情中列出。

来源为用户表格的69条记录：68条数据集类登记、1条模型类登记。它们不是69个已取得且可直接使用的数据集。研究大类和细分类沿用表格，不新增未经证实的疾病诊断或模型训练关联。

7条数据集记录已接入113个共享文件入口，使用 `/data/share/datasets/<数据集名称>/<原文件名>`。部分资源尚未接入全部文件，卡片逐项说明范围。Coswara 显示一个文件夹，43个分包放在详情中。此前误增的46条平铺链接和2条单数别名已按用户后续授权清理。

其余状态包括已有目录、授权／权限待确认、共享存储待确认、尚无落盘入口、其他机器、下载未完成。只有共享入口经过两机核验的记录才给出本次接入路径。原始数量与版本说明保留来源口径，不把文件数当样本数。

## 维护文件

`data/resource-directory.json` 是本地分类快照的单一来源，保存 name、kind、category、subcategory、status、note、shared_directory、files、source 等字段。

- 补充分类：编辑 category、subcategory；新的值会进入筛选框。
- 接入资源：先核对许可和两机文件入口，再更新 shared_directory、files 和 linked_file_count。
- 增加记录：使用不重复的稳定 id，并记录来源行或新增来源。
- 保留旧目录清册，避免把表格登记 ID 自动当作旧门户 asset_id；身份合并应单独核验。
- 文件数量由 files 列表确定，目录扫描和实时监控尚未部署。
- 读取接口每次读取快照；网页通过顶部刷新重新加载。
- 该文件不含个人原始路径、申请凭证或操作日志，不代表已批准公网发布。

## API

沿用现有平台鉴权：

- `GET /api/classified-resources`
- `GET /api/classified-resources/{id}`
- `GET /api/classified-resources/{id}/README.md`

列表支持 q、kind、category、subcategory、status；同一参数不允许重复。返回 total、items 和 facets；当前为小型快照接口，不提供原始数据下载或写入。

```sh
curl -H "Authorization: Bearer $RDC_TOKEN" \
  'http://127.0.0.1:8765/api/classified-resources?status=shared'
```

Agent README 按相同记录生成，包含使用边界、分类、共享目录和文件列表。元数据文本作为资料处理，不作为可执行指令。

## 测试与发布

新增3项测试通过：资源与文件计数区分、非法筛选拒绝、HTTP鉴权／README／只读边界。原有目录接口5项测试通过；JavaScript语法检查通过。浏览器工具连续连接超时，本轮未完成视觉验收。

打包脚本已包含 resource_directory.py 和 data/resource-directory.json，安装器已允许新模块。完整生产发布尚未执行，不修改远端程序、权限、服务或定时任务。

本轮仅在远端执行经过授权的目录与软链接操作；页面和接口改动保存在新仓库中。

后续补充、直接上传规则、分类标签和私有监控日志见 [共享目录工作流](storage-catalog-workflow.md)。
