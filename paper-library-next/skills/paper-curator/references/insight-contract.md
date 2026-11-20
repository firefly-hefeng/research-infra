# 已有文献导读契约

`insight` 是附在已有论文记录上的阅读补充，单独保存在 SQLite 的 `paper_insights` 表。它不替换导入题录或原卡片，也不更改分类、归档路径、收藏和笔记。现有公开目录会返回此字段；没有导读时为 `null`。

## 结构

```json
{
  "schema_version": 1,
  "source_digest": "目标论文的完整64位SHA-256 ID",
  "abstract": {
    "status": "available",
    "text": "保留原语言的完整摘要，不能填写翻译或缩写",
    "language": "en",
    "pages": [1]
  },
  "keywords": ["主题词一", "主题词二", "主题词三"],
  "keywords_source": "curated",
  "summary": {
    "overview": "用中文说明论文研究什么、怎么做以及主要发现。",
    "problem": "研究要解决的问题及其情境。",
    "method": "主要方法与关键步骤之间的关系。",
    "findings": "有原文支持的发现，保留条件和结果范围。",
    "limitations": "原文明确提到的局限；没读到时留空。"
  },
  "evidence": [
    {"field": "summary.overview", "page": 1, "quote": "来自本页的连续逐字原文"}
  ],
  "coverage": "abstract",
  "generated_by": "codex"
}
```

上例仅说明形状，不是可提交内容：每个非空 `summary` 字段都需要自己的真实证据条目。不要复制示例值充当论文信息。

- `schema_version`：整数 `1`。
- `source_digest`：可以省略，由保存程序绑定为目标论文 ID。若提供它或 `paper_id`，必须与命令的 ID 及批量文件名一致。程序还会核对当前 PDF 字节的 SHA-256。
- `abstract.status`：`available` 或 `missing`。`available` 时需提供 `text`、`language` 和 `pages`；`language` 为 `en`、`zh` 或 `other`。`pages` 为从 1 开始的物理 PDF 页码，1–6 项、连续递增且不重复；摘要文本最多 24,000 字符。跨页摘要按原顺序合并，不增删摘要内容。若提取顺序中夹有页眉、页脚、通讯信息，可提供可选 `abstract.segments: [{"page":1,"text":"该页完整摘要段落"},{"page":2,"text":"后续摘要段落"}]`；每段必须在该页连续匹配且顺序不变，`text` 必须严格等于各段按顺序拼接的文本（仅允许空白差异），`pages` 必须与片段覆盖页一致。只剔除版面噪声，不能借此删减真正摘要。
- 没有可可靠提取的摘要时使用 `{"status":"missing","reason":"具体缺失原因"}`；原因最多 1,000 字符，不再填其他摘要字段。不能把引言、已有短简介或模型生成的总结称作原文摘要。
- `keywords`：3–8 个不重复的主题词，每个最多 80 字符；摘要缺失且没有可靠内容可归纳时允许空列表。`keywords_source` 仅支持 `curated`，省略时也是该值，表示整理者归纳。
- `summary`：仅包含上例五个字段，每项最多 6,000 字符，均使用中文，保留必要的英文模型名和缩写。有摘要时 `overview` 必填，其他字段可为空或省略。摘要缺失时允许全部留空，也可以依据已读正文写有证据的总结。
- `evidence`：最多 50 项。`field` 只能是上述 `summary.<字段>`；每个非空总结字段至少一条。`page` 为该引文所在的物理页，`quote` 为连续逐字原文，8–6,000 字符。跨页论断可附多条分别定位的证据。空总结字段不附证据。不得仅因为某页有关键词就用它支持不相干的结论。
- `coverage`：`abstract` 表示只依据摘要，所有证据必须位于摘要内；`selected_pages` 表示读了正文中的部分页；`full_text` 仅在实际读完全文时使用。摘要缺失时不能同时声称基于摘要生成了非空总结。
- `generated_by`：如实填写 `codex`、`agent`、`api` 或 `manual`。`updated_at` 由保存程序设置；输入值不会决定更新时间。

## 读取与保存

在项目根目录运行，始终使用同一个 `PAPER_ROOT` 或 `--root`：

```sh
python3 manage.py extract-insight <ID>
python3 manage.py commit-insight <ID> <导读JSON路径>
python3 manage.py import-insights <批量JSON目录> --check
python3 manage.py import-insights <批量JSON目录>
```

`extract-insight` 使用不带 `-layout` 的 `pdftotext`，保留 `\f` 分页。普通阅读顺序文本缓存在 `.paperlib/insights/source/<ID>.txt`，与旧卡片 `.paperlib/text/` 缓存分开；空文本的英文扫描件可在安装 Tesseract 后自动 OCR（最多 30 页），输出 `source_method: "ocr"`，须结合页面图像核对识别错误。普通 PDF 输出 `source_method: "pdf_text"`，该字段由程序决定；不要用另一种排版的提取结果猜证据页内顺序。

批量目录只放 `<ID>.json` 文件，单文件最大 160 KB，不允许符号链接和重复 JSON 字段。`--check` 不保存导读，但可能生成正文缓存和批次校验日志。非检查模式逐篇校验并保存，一篇失败不会覆盖其旧导读，后续条目继续处理；任何失败都会使 CLI 返回非零退出码。日志位于 `.paperlib/insights/import-*.json`，权限 `0600`，包含逐项结果，不保存模型凭据或请求内容。

## 校验边界

程序按 Unicode 规范化、大小写与空白归一化后匹配原文摘要和引文，拒绝编造、翻译替代或无法连续匹配的片段。它不能自动判定摘要是否完整，也不能证明中文总结准确：整理者仍须核对摘要标题与结束位置、跨栏或跨页顺序，以及每项发现与其原文条件。已有题录短说明只能作为线索，不能作为原文证据。

双栏 PDF 的纯文本顺序偶尔与页面阅读顺序相反。仅在对照页面确认后，允许设置 `abstract.segment_order: "reading_order"`，在同一页内调整 `segments` 顺序；每段仍须逐字匹配且不能重叠，跨页页码保持递增。默认按提取顺序验证，不自动重排摘要。
