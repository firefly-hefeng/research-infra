# 科研周记：姓名登记 + 日报与周报 + Agent 周报汇总

## 当前工作方式

1. 首次在网页填写姓名后加入；已有登记直接选择，同名者需附加组别等区分信息。原配置中的成员继续保留。
2. 周报网页只接收文件，不提供在线填写；成员选择姓名和周次后上传任意扩展名的文件。日报仍支持在线填写或上传模板 Markdown。
3. 上传同时检查名单与目录是否存在；上传不会代为登记。姓名登记走独立接口，随机生成目录 ID，不接受用户指定路径。
4. 原始周报保存在 `members/<id>/uploads/YYYY-Www.original<ext>`，处理状态保存在同目录 JSON 中。合规标准 Markdown 直接进入 `reports/YYYY-Www.md`；其他文本、Office、PDF 和图片进入智能整理队列。
5. Agent 将可解析内容整理为“本周完成、结果与证据、问题与阻塞、下周计划”，通过原有模板校验后才写入正式周报。无法可靠解析或内容冲突时保留原件并标记 `needs_review`，不会伪造进度或覆盖旧报告。
6. Agent / Skill 汇总标准周报，发布团队概要及逐人进展。团队报告与知识库只读，待整理原件与正式提交分开统计。

日报单独保存到 `members/<id>/daily/YYYY-MM-DD.md`，包含今日完成、结果与证据、问题与阻塞、明日计划。日报不会自动转换为周报，也不会混入现有每周汇总输入。入口支持 `#daily` 直接定位。

新增姓名保存在配置的 `state` 根下 `members.json`，不修改服务配置。HTTP 服务和周报汇总命令均读取该持久名单；备份需同时包含 state 与 members。重名返回 409，不会认领已有目录。登记仅是成员标签，不是身份认证。

新增接口：`POST /api/members`（JSON 只含 `name`）；`GET /api/daily-template?member_id=...&date=YYYY-MM-DD`；`POST /api/daily/uploads`（JSON 的 `member_id`、`date`、`fields`，或 multipart 的 `member_id`、`date`、一个 `file`）；`GET /api/upload-status?member_id=...&week=...` 只返回周报处理状态，不返回原件或私有路径。所有写请求沿用 `X-Requested-With: ResearchWeekly` 和原来源限制。日报同日相同内容幂等返回 200，首次 201，不同内容 409。

**无登录意味着不能验证实际上传者身份。** 任何能访问服务的人都可以选取已开放的成员目录提交，也可以阅读团队总结和知识库。选择成员不是登录，目录检查不是身份认证。原始个人报告和上传原件没有 HTTP 读取、编辑、删除接口；旧版账号数据库、草稿和笔记保留在磁盘，但不再通过网页开放。正式环境适用于团队内网或已有网络访问边界。上传文件不会被执行或作为静态内容发布。

每人每周一份：首次提交返回 201；完全相同内容重复上传返回 200；不同内容返回 409，不能匿名覆盖。更正由维护人员备份旧文件后直接修改，再重跑该周汇总。网页没有草稿功能，提交前请保留本地文件。

## 本地运行

需要 Python 3.11+。首次运行：

```bash
cd research-progress
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m research_weekly.cli demo
.venv/bin/python -m research_weekly.cli serve
```

已有数据时直接运行 `serve`，不必重跑 `demo`。访问 http://127.0.0.1:8765，无需账号密码。
`demo` 是显式初始化示例目录、虚构周报和规则摘录的命令，不覆盖原始周报，但可能重新生成演示汇总。真实智能总结需配置 Agent 或模型 API。

## 登记成员与目录

修改配置中的 `members`：

```json
[{"id":"lin","name":"林同学"},{"id":"chen","name":"陈同学"}]
```

ID 为 2–32 位小写字母、数字、下划线或连字符，以字母开头。然后维护人员显式初始化：

```bash
.venv/bin/python -m research_weekly.cli --config config.demo.json init
```

`init` 为名单里的成员建立目录，不需要设置密码。修改名单后重启 Web 服务。
也可以由维护人员手动建立 `members/<id>/`；上传时会在已存在的成员目录内建立 `reports/`。仅有目录但未在名单中登记也不能上传，保证 Agent 汇总名单一致。
**`serve`、`prepare`、`summarize` 均不自动补建缺失成员目录。**

目录路径由 `paths.members/team/knowledge/state` 配置。相对路径基于配置文件所在目录；四个根目录不能互相嵌套或使用符号链接。目录变化不会自动迁移数据。

```text
data/
├── members/<id>/reports/YYYY-Www.md  # 个人正式周报，不开放 HTTP 读取
├── team/weekly/YYYY-Www.md           # 共享总结
├── team/weekly/YYYY-Www.json         # 前端元信息
├── knowledge/*.md                   # 共享知识，维护人员更新
└── .state/jobs/、history/            # 私有原始输入、结果及历史
```

## 模板 v1

网页先选成员和周次，再点击“下载对应模板”。四个二级标题必须按以下顺序出现一次，内容不能为空；未知写“未说明”。下载的填写提示必须替换后才能提交。一级标题必须与配置姓名和目标周次匹配。

```markdown
# 林同学 · 2026-W42 科研周报

## 本周完成
完成语音样本字段检查，正在核对设备信息。

## 结果与证据
已生成数据核对清单；尚未进行模型性能对比。

## 问题与阻塞
部分设备信息需要补充。

## 下周计划
补齐字段后开展小批量特征提取验证。
```

模板规则在 `research_weekly/reports.py`，网页、API、Agent 收集器共用。既有示例报告兼容此格式。直接写磁盘的报告也必须合规，否则汇总失败，旧团队总结继续保留。单报告默认 64 KB，每栏目最多 12000 字；总汇总输入默认 512 KB。只有符合此模板的 UTF-8 Markdown 可跳过智能整理直接入正式周报，其他格式由 Agent 整理后仍须通过同一校验。

## 前后端统一上传接口

### 读取公开信息和模板

```text
GET /api/public
GET /api/report-template?member_id=lin&week=2026-W43
GET /api/upload-status?member_id=lin&week=2026-W43
GET /api/team
GET /api/team/2026-W42
GET /api/knowledge
GET /api/knowledge/01-欢迎加入.md
```

`/api/public` 返回当前可上传成员、周次、时区、正式报告与原始文件大小限制，不返回磁盘绝对路径或原始周报。

### 上传任意格式文件

```bash
curl --fail-with-body http://127.0.0.1:8765/api/uploads \
  -H 'X-Requested-With: ResearchWeekly' \
  -F 'member_id=lin' \
  -F 'week=2026-W43' \
  -F 'file=@./2026-W43.docx'
```

接收接口不限制扩展名，默认原件上限 20 MiB，可用 `summary.max_upload_bytes` 调整。文件名不能包含路径或父目录标记。标准 Markdown 直接校验；文本、DOCX/PPTX/XLSX、PDF 和图片进入自动整理；其他二进制格式保存原件并标记待人工整理。处理状态通过 `/api/upload-status` 查询。

### 后端脚本发送结构化字段（兼容接口）

```bash
curl --fail-with-body http://127.0.0.1:8765/api/uploads \
  -H 'Content-Type: application/json' \
  -H 'X-Requested-With: ResearchWeekly' \
  --data-binary @- <<'JSON'
{
  "member_id": "lin",
  "week": "2026-W43",
  "fields": {
    "done": "完成样本字段检查",
    "results": "生成数据核对清单，未进行性能对比",
    "blockers": "设备信息需要补充",
    "next": "补齐字段后验证特征提取"
  }
}
JSON
```

周报网页不再使用 JSON 表单，仅为已有自动化脚本保留该兼容接口。文件上传使用 multipart，不要把 `fields` 放进 multipart，也不要把文件路径放进 JSON。

| 状态 | 含义 |
|---|---|
| 201 | 新原件或正式报告已存入个人目录 |
| 200 | 同内容已存在，幂等成功 |
| 400 | 模板、字段、成员 ID、周次、文件名或编码错误 |
| 403 | 成员未登记、目录不存在、缺请求头或 Origin 不允许 |
| 409 | 同成员同周已有不同内容，禁止覆盖 |
| 413 | 上传超过大小限制 |
| 415 | 不支持的请求类型 |

文件提交成功返回 `ok, duplicate, member_id, week, sha256, upload_sha256, summary_status, status_detail`，不返回原始内容和服务器路径。
没有会话 Cookie、密码或 CSRF Token。所有上传须带固定 `X-Requested-With`，浏览器的 Origin 须匹配配置；这用于阻止外站网页直接提交，不是用户身份认证。跨域前端暂不开放 CORS，当前网页与 API 同源部署；后端程序可直接调用。

## Skill 与模型接入

Skill：`skills/research-weekly-summary/SKILL.md`，环境变量 `RESEARCH_PROJECT` 为项目目录，`RESEARCH_CONFIG` 为配置绝对路径。

手动工作流：

```bash
.venv/bin/python -m research_weekly.cli --config config.demo.json prepare --week 2026-W42
# Agent 读取返回 job 内的 prompt.txt 与 manifest.json，写入 result.json
.venv/bin/python -m research_weekly.cli --config config.demo.json publish \
  --job /实际/job/路径 --result /实际/job/路径/result.json
```

自动工作流：

```bash
.venv/bin/python -m research_weekly.cli --config config.deepseek.local.json process-uploads --once
.venv/bin/python -m research_weekly.cli --config config.deepseek.local.json summarize --week previous
```

`current` 为配置时区本周，`previous` 为上一周，也支持明确 `YYYY-Www`。相同输入、同生成方式跳过发布；有意重跑用 `--force`。输入在运行中变化则拒绝发布旧结果。网页上传只保存原件并排队，不在 HTTP 请求中调用付费模型；intake worker 整理成功后触发对应周次汇总，失败保留旧团队报告。

- **API 模式**：`summary.mode=api`，配置 `api_base`、`model`、`api_key_env`。生产使用 `https://api.deepseek.com`、`deepseek-flash` 和 `DEEPSEEK_API_KEY` 环境变量，不保存密钥到配置。整理与汇总程序请求 `{api_base}/chat/completions`，要求严格 JSON 输出。
- **CLI Agent**：`summary.mode=agent`，配置 argv 数组 `agent_command`。支持 `{prompt_file}`、`{result_file}`、`{work_dir}`、`{skill_file}`。适配程序读取提示词、调用 Agent、将纯 JSON 写入结果文件并返回 0。
- **规则演示**：`summary.mode=extractive` 只允许演示环境，不是 AI 总结。

## Linux 部署与定时

1. 将项目放到 `/opt/research-progress`，排除 Mac 的 `.venv`、演示 `data`；用 Python 3.11+ 重建环境，安装 `requirements.lock.txt`。
2. 创建专用系统用户 `research-weekly`，拥有 `/srv/research-progress`，目录权限 0700。成员无需服务器账户。
3. 复制 `config.linux.example.json` 到 `/etc/research-weekly/config.json`。填写成员、数据路径、实际域名 `security.allowed_origins` 与模型配置；保持 `demo=false`、`security.https=true`。旧 `secure_cookies` 字段兼容读取，但不再使用 Cookie。
4. 创建 `/etc/research-weekly/environment`，配置 `RESEARCH_CONFIG` 和模型环境变量，权限 0600。使用 DeepSeek 时填 `DEEPSEEK_API_KEY`，不是只在个人终端 export，也不要把密钥写进 JSON 配置或源码。
5. 在项目目录以服务用户运行 `init`，显式建立成员文件夹，无需设置密码。
6. 将 `deploy/` 的 intake、summary systemd service/timer 安装到 `/etc/systemd/system/`，Web 单元增加同一个 `EnvironmentFile`；若目录变化，同步调整 `WorkingDirectory`、`ExecStart`、`ReadWritePaths`。
7. Nginx 提供 HTTPS，代理到 `127.0.0.1:8765`，参考 `deploy/nginx.example.conf`。不要将 data 映射为静态目录。无登录时访问范围由部署网络决定。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now research-weekly-web.service
# 配好模型后先在隔离数据上验收，再启用定时：
sudo systemctl start research-weekly-intake.service
sudo systemctl start research-weekly-summary.service
sudo journalctl -u research-weekly-intake.service -u research-weekly-summary.service -n 50
sudo systemctl enable --now research-weekly-intake.timer research-weekly-summary.timer
systemctl list-timers research-weekly-intake.timer research-weekly-summary.timer
```

intake timer 每分钟扫描待整理原件；summary timer 默认每周一 09:00 Asia/Shanghai 汇总上一周。修改 timer 后 daemon-reload 并 restart 对应 timer。`Persistent=true` 只补一次触发，不逐周补齐所有历史。

CLI Agent 应使用绝对路径；systemd 的凭据和 HOME 属于服务用户，不继承个人终端会话。单机本地磁盘运行，依赖 `fcntl`，未验证多机共享盘。旧 `.state/auth.sqlite3` 不再使用但不会自动删除；备份应覆盖所有数据根目录。暂未提供发布审批、告警或历史清理界面。

## 验证

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --check web/app.js
```

测试覆盖无登录公开读取、原始报告不开放、目录不存在拒收、未知成员、模板及编码校验、任意格式原件、同内容幂等、禁止覆盖、路径与符号链接、Office/PDF 提取、图片多模态请求、状态迁移、待整理统计、Agent 命令与失败保留旧总结。模型调用在测试中全部模拟；模型归纳的科研事实仍须核对原文。

## 已部署为资源中心模块

已在 `rmp@101.132.97.146` 的 `/data/rmp/research-progress` 部署，挂到科研管理中心 `/progress/`。2026-10-31 升级周报全格式上传与 DeepSeek 智能整理，保留日报、成员、团队报告和知识库数据，并配置 intake 与 summary 定时任务。模型密钥仅由 systemd 环境文件注入。
