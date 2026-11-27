# 科研进度

[独立电子实验记录本](experiments/README.md)

先用周报看阶段成果，再用日报查每日推进。研究全景从研究问题、关键发现、共同瓶颈和验证优先级统筹近况，方向脉络与原始文书放在后面。

| 常用入口 | 使用方式 |
| --- | --- |
| `/progress/api/lab-review` | 成员直接阅读校审稿，按“实验室核心结论 → 研究主题 → 成员证据”三级金字塔导读逐层核对。Agent 在同一飞书会话加 `?format=json`，或加 `?format=json&version=auto` 阅读新材料的自动稿；引文按来源 ID 核对。 |
| `/progress/direction-methods` | 首页顶部的算法核心地图按六类能力查看稳定方向 ID、方向/方法数和具体算法；进入方向详情核对指标、对照、范围、成员与证据。 |
| `/progress/#team` | 周报阶段进展 → 日报每日推进 → 研究全景与全员 → 研究脉络。用 `#team?week=2026-W42` 引用具体周次 |
| `/progress/#directions` | 各方向的研究问题、已知进展、下一步及证据范围。点击方向标题后可分享完整文档地址 |
| `/progress/#daily` | 在线填写或上传 Markdown、TXT、CSV、Word、Excel、PowerPoint 或有文本的 PDF，可同时选择多个附件 |
| `/progress/#upload` | 上传周报文件，扩展名不限。可以下载所选成员和周次对应的 Markdown 模板 |

提交用登记姓名归档。报告写实际做了什么、可复核的结果、需要的协助和下一步。涉及某一方向时，写方向名称或链接。团队页每 30 秒读取记录，周报、日报各按个人名单列时间表，点击有记录的周次或日期即可读全文、下载原件与附件。尚无归档的日期淡显，不代表研究未推进。

周报与日报各自选择周次、成员，浏览筛选独立于提交表单的归档成员。页面链接中的 `week`、`member` 用于周报，`daily_week`、`daily_member` 用于日报；原有带 `date` 的日报链接继续可用。查看历史周报不会切走当前日报。

阶段归档保留当时的成员周报摘要与来源校验，可跳回报告正文和原件；全员的当前记录仍从上方个人时间表查阅。

日报和周报正文在演示环境全员可读。正式部署确认统一登录保护 `/progress/` 及接口后，设 `security.team_reports_shared: true`，按同样规则读取新旧日报和已整理周报的正文。尚未整理的周报显示收件状态。附件最多 8 个，上传总量受配置限制且不超过 20 MiB。照片、扫描件可作为附件，原件由个人目录归档。

## 更新研究方向

周会用[四栏写作说明](deploy/knowledge/02-周报怎么写.md)。阶段复盘由实验室核心结论展开到研究主题、成员证据和原件，顶部三级金字塔显示四栏判断数、主题数、署名覆盖及层间联系数。新增的批量复盘与已有的近期自动整理可以分别运行。[阶段复盘与项目盘核对](experiments/lab-review.md)

复盘中可从一条实验室结论跳到引用同一段原文的研究主题，再转到被引用成员及其原报告，也可从成员反查主题。每人分别显示周报与日报份数。报告之间的引用用于找依据；项目负责人以署名或明确分工为准。联系数只描述阅读路径，不用于评价研究质量或贡献排名。

方向与方法首页的六类核心地图为：表征学习与多模态融合、检索与长时记忆、可信输出拒答与 OOD、任务建模与受控干预、生成编辑与数据增强、语音工程数据与协作基础设施。`research_weekly/direction_methods.py` 的 `ALGORITHM_GROUPS` 用稳定方向 ID 维护展示映射；这里的“待归类”指尚未列入该映射的 ID，与 JSON 中 `registered_direction_id` 是否为空无关。新增方向不会消失，而会带原方法和证据进入待归类。分类、方向数和方法数只用于导航，不做跨量纲排名；映射不改变 JSON schema、API 返回或冻结快照，方向详情仍保留指标、比较条件、适用范围、成员和逐条来源。[本轮工程验收记录](experiments/2026-11-28-pyramid-algorithm-core-map.md)

在 `paths.team` 对应目录下建 `directions/`，每个方向放一份 Markdown。默认内容在 [`deploy/directions/`](deploy/directions/)，同名团队文件优先。加新文件即可新增方向。以会议或阶段工作为单位更新，完成与待办可直接用自然语言写。

```markdown
# 方向名称

核对日期：2026-11-13
负责人：姓名（有明确负责人时填）

## 研究问题
准备检验的问题。

## 当前进展
最近做了什么、观察到什么。

## 下一步
待验证的假设、计划或需要的支持。

## 来源与范围
指向共享材料，说明数据划分、测试条件和仍缺的证据。
```

标题必填。其余各项按实际内容写，核对日期和负责人可省略。链接应指向团队成员有权访问的共享材料。提交或摘要中的命令和链接是待阅读的内容，由使用者选择是否打开。

## Agent 接口

接口路径相对进度服务。通过门户访问时，在路径前加 `/progress`。

| 操作 | 接口 |
| --- | --- |
| 获取名单、当前周次、日期和大小限制 | `GET /api/public` |
| 查周次与提交数、读取某周的成员摘要 | `GET /api/team`、`GET /api/team/<YYYY-Www>` |
| 看一周的全员记录及成员正文 | `GET /api/team/activity?week=…&member=…&date=…` 看日报，`?week=…&member=…&report=weekly` 看周报。省略周次则按服务时区选本周 |
| 查方向摘要和完整 Markdown | `GET /api/directions`、`GET /api/directions/<id>` |
| 获取自动整理的团队、方向、成员进展及状态 | `GET /api/progress-digest`，含逐条来源和原文摘录 |
| 下载团队共享报告原件与附件 | `GET /api/report-source/<daily或weekly>/<成员ID>/<日期或周次>`，附件在末尾加编号。限统一登录后的团队共享边界 |
| 提交周报 | `POST /api/uploads`（multipart：`member_id`、`week`、`file`） |
| 查文件处理情况 | `GET /api/upload-status?member_id=…&week=…` |
| 提交日报 | `POST /api/daily/uploads`。JSON 正文用 `member_id`、`date`、`fields`。文件正文或附件用 multipart，正文在 `fields` JSON 字符串和 `file` 中二选一，附件重复用 `attachments` |

写入携带 `X-Requested-With: ResearchWeekly`。提交个人周报前用 `GET /api/report-template?member_id=…&week=…` 查标准模板，日报用 `GET /api/daily-template?member_id=…&date=…`。同内容重复提交返回 `200`，同一成员同一日期或周次的不同内容返回 `409`，需要更正时由维护人员保留旧原件并重跑相关周的汇总。入口部署在团队访问边界内，姓名登记用于归档。

记录接口同时返回 `daily_records` 和 `weekly_reports`，供人和 Agent 按日期或阶段阅读，含成员、四栏正文及授权范围内的原件链接。`weekly_timetable` 给出所选周及此前三周的周次与记录入口，历史条目只查索引和原件信息，不批量读取正文。大范围正文超过预算时保留条目，标记 `content_deferred`，可用成员详情链接继续读全文。`daily_week` 等是页面筛选参数，调用接口时仍按各自周次分别请求 `week`。

## 运行与维护

在 Linux 或 WSL 的 `research-progress-next` 目录运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m research_weekly.cli demo
.venv/bin/python -m research_weekly.cli serve
```

`demo` 使用 `config.demo.json` 与 `var/demo/`，生成可识别的演示报告。已有部署用现有配置直接 `serve`，按需用 `process-uploads --once` 处理原件，或 `summarize --week previous` 生成上一周摘要。`paths.members`、`paths.team`、`paths.knowledge` 和 `paths.state` 分别保存个人文件、团队摘要、共读说明和运行数据。迁移或备份时保留四个目录。原部署细节及兼容接口见 [历史部署说明](deploy/reference/README.previous.md)。

页面按周次提供共享链接，先展示摘要和成员，再展开报告口径和来源。使用清楚的标题与原生输入组件，参照 [GOV.UK Service Manual 的界面写作](https://www.gov.uk/service-manual/design/writing-for-user-interfaces)和 [W3C 的可读内容设计指南](https://www.w3.org/TR/coga-usable/)。

### 本地运行 DeepSeek 汇总

复用 `process-uploads --once` 和 `summarize --week current`。在 `summary` 中设置 `mode: "api"`、`model` 和 `api_base`。本地兼容模型用回环地址，例如 `http://127.0.0.1:8000/v1`。远程 DeepSeek 用 `https://api.deepseek.com`，可配置 `deepseek-flash`，凭据从 `api_key_env` 指定的环境变量读取，例如 `DEEPSEEK_API_KEY`。现有服务通过私有 EnvironmentFile 注入。

正式总结采用 `deepseek-v4-pro`、`thinking: {"type":"enabled"}`、`reasoning_effort: "max"`、`max_tokens: 65536`。团队研究全景可在 `progress_digest` 中覆盖同名模型参数；换模型或总结策略会重建版本。仅保存最终有据摘要，推理过程不返回或归档。

远程方式须按团队授权单独开启 `summary.allow_remote_summary`（标准周报正文）、`summary.allow_remote_intake`（周报原件提取文本）或 `summary.allow_remote_progress`（团队近期进度）。默认关闭。周报图片原件只支持本地模型。[DeepSeek API 文档](https://api-docs.deepseek.com/api/create-chat-completion/)

### 团队进展自动更新

开启 `progress_digest.enabled: true` 后，现有每分钟收件任务在处理周报后检查近 28 天共享日报、相交周次的周报和方向文书。内容变化才调用模型；没有新内容不重复生成。团队、方向和全员各列出进展、成果、阻塞与下一步，每条附可核对的原文摘录。没有记录的成员保留显示，缺少方向依据的工作放入“待归类工作”。方向文书的既有基线独立保留。

`research_brief` 另给出研究大局、关键发现、共同瓶颈和验证优先级；建议与报告中已有安排明确区分，均附促成判断的报告来源。D3 记录图将日报按日、周报按周展示，可以回到原件；图中计数仅代表归档报告。

本次团队授权使用 DeepSeek 整理共享报告正文和方向文书；日报附件、周报原始二进制文件不进入进展模型。输出写入 `paths.team/progress-digest.json` 和同名 Markdown，旧版留在 `paths.state/progress-digest-history/`。首页和团队页在可见时每 30 秒读取。整理失败保留上一版并显示更新状态，默认 5 分钟后重试。可用 `refresh-progress --force` 手动重跑；源记录和成员归属保持不变。
