# 科研周记：姓名登记 + 日报与周报 + Agent 周报汇总

## 当前工作方式

1. 首次在网页填写姓名后加入；已有登记直接选择，同名者需附加组别等区分信息。原配置中的成员继续保留。
2. 成员打开网页，无需登录，选择报告所属成员及日期或周次，在线填写或上传模板 Markdown。
3. 报告上传同时检查名单与目录是否存在；上传不会代为登记。姓名登记走独立接口，随机生成目录 ID，不接受用户指定路径。
4. 报告按统一格式存入 `members/<id>/reports/YYYY-Www.md`。
5. Agent / Skill 每周收集标准周报，发布团队概要及逐人进展。团队报告与知识库只读。

日报单独保存到 `members/<id>/daily/YYYY-MM-DD.md`，包含今日完成、结果与证据、问题与阻塞、明日计划。日报不会自动转换为周报，也不会混入现有每周汇总输入。入口支持 `#daily` 直接定位。

新增姓名保存在配置的 `state` 根下 `members.json`，不修改服务配置。HTTP 服务和周报汇总命令均读取该持久名单；备份需同时包含 state 与 members。重名返回 409，不会认领已有目录。登记仅是成员标签，不是身份认证。

新增接口：`POST /api/members`（JSON 只含 `name`）；`GET /api/daily-template?member_id=...&date=YYYY-MM-DD`；`POST /api/daily/uploads`（JSON 的 `member_id`、`date`、`fields`，或 multipart 的 `member_id`、`date`、一个 `file`）。所有写请求沿用 `X-Requested-With: ResearchWeekly` 和原来源限制。日报同日相同内容幂等返回 200，首次 201，不同内容 409。原周报接口不变。

**无登录意味着不能验证实际上传者身份。** 任何能访问服务的人都可以选取已开放的成员目录提交，也可以阅读团队总结和知识库。选择成员不是登录，目录检查不是身份认证。原始个人报告没有 HTTP 读取、编辑、删除接口；旧版账号数据库、草稿和笔记保留在磁盘，但不再通过网页开放。正式环境适用于团队内网或已有网络访问边界。

每人每周一份：首次提交返回 201；完全相同内容重复上传返回 200；不同内容返回 409，不能匿名覆盖。更正由维护人员备份旧文件后直接修改，再重跑该周汇总。没有网页草稿功能，提交前请保留本地文件。

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

模板规则在 `research_weekly/reports.py`，网页、API、Agent 收集器共用。既有示例报告兼容此格式。直接写磁盘的报告也必须合规，否则汇总失败，旧团队总结继续保留。单报告默认 64 KB，每栏目最多 12000 字；总汇总输入默认 512 KB。只支持 UTF-8 Markdown。

## 前后端统一上传接口

### 读取公开信息和模板

```text
GET /api/public
GET /api/report-template?member_id=lin&week=2026-W43
GET /api/team
GET /api/team/2026-W42
GET /api/knowledge
GET /api/knowledge/01-欢迎加入.md
```

`/api/public` 返回当前可上传成员、周次、时区与大小限制，不返回磁盘绝对路径或原始周报。

### 上传 Markdown 文件

```bash
curl --fail-with-body http://127.0.0.1:8765/api/uploads \
  -H 'X-Requested-With: ResearchWeekly' \
  -F 'member_id=lin' \
  -F 'week=2026-W43' \
  -F 'file=@./2026-W43.md'
```

必须是一个 `.md` 文件，标题须匹配林同学与 2026-W43。文件名不决定存储路径，后端统一按周次命名。

### 后端脚本发送结构化字段

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

网页在线表单使用同一个 JSON 接口，文件上传使用同一个 multipart 接口。不要把 `fields` 放进 multipart，也不要把文件路径放进 JSON。

| 状态 | 含义 |
|---|---|
| 201 | 新报告已存入个人目录 |
| 200 | 同内容已存在，幂等成功 |
| 400 | 模板、字段、成员 ID、周次或编码错误 |
| 403 | 成员未登记、目录不存在、缺请求头或 Origin 不允许 |
| 409 | 同成员同周已有不同内容，禁止覆盖 |
| 413 | 上传超过大小限制 |
| 415 | 不支持的请求类型 |

提交成功返回 `ok, duplicate, member_id, week, sha256, template_version`，不返回原始内容和服务器路径。
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
.venv/bin/python -m research_weekly.cli --config config.deepseek.local.json summarize --week previous
```

`current` 为配置时区本周，`previous` 为上一周，也支持明确 `YYYY-Www`。相同输入、同生成方式跳过发布；有意重跑用 `--force`。输入在运行中变化则拒绝发布旧结果。上传本身不会触发付费模型调用，也不会创建定时任务。

- **API 模式**：`summary.mode=api`，配置 `api_base`、`model`、`api_key_env`。DeepSeek 本地配置引用 `DEEPSEEK_API_KEY` 环境变量，不保存密钥。程序请求 `{api_base}/chat/completions`，需要兼容 JSON 输出契约。
- **CLI Agent**：`summary.mode=agent`，配置 argv 数组 `agent_command`。支持 `{prompt_file}`、`{result_file}`、`{work_dir}`、`{skill_file}`。适配程序读取提示词、调用 Agent、将纯 JSON 写入结果文件并返回 0。
- **规则演示**：`summary.mode=extractive` 只允许演示环境，不是 AI 总结。

## Linux 部署与定时

1. 将项目放到 `/opt/research-progress`，排除 Mac 的 `.venv`、演示 `data`；用 Python 3.11+ 重建环境，安装 `requirements.lock.txt`。
2. 创建专用系统用户 `research-weekly`，拥有 `/srv/research-progress`，目录权限 0700。成员无需服务器账户。
3. 复制 `config.linux.example.json` 到 `/etc/research-weekly/config.json`。填写成员、数据路径、实际域名 `security.allowed_origins` 与模型配置；保持 `demo=false`、`security.https=true`。旧 `secure_cookies` 字段兼容读取，但不再使用 Cookie。
4. 复制 `deploy/environment.example` 到 `/etc/research-weekly/environment`，配置 `RESEARCH_CONFIG` 和模型环境变量，权限 0600。使用 DeepSeek 时填 `DEEPSEEK_API_KEY`，不是只在个人终端 export。
5. 在项目目录以服务用户运行 `init`，显式建立成员文件夹，无需设置密码。
6. 将 `deploy/` 三个 systemd 文件安装到 `/etc/systemd/system/`；若目录变化，同步调整 `WorkingDirectory`、`ExecStart`、`EnvironmentFile`、`ReadWritePaths`。
7. Nginx 提供 HTTPS，代理到 `127.0.0.1:8765`，参考 `deploy/nginx.example.conf`。不要将 data 映射为静态目录。无登录时访问范围由部署网络决定。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now research-weekly-web.service
# 配好模型后手动验收一次，再启用定时：
sudo systemctl start research-weekly-summary.service
sudo journalctl -u research-weekly-summary.service -n 50
sudo systemctl enable --now research-weekly-summary.timer
systemctl list-timers research-weekly-summary.timer
```

默认每周一 09:00 Asia/Shanghai 汇总上一周。修改 `research-weekly-summary.timer` 的 `OnCalendar` 后 daemon-reload 并 restart timer。`Persistent=true` 补一次触发，不逐周补齐所有历史。本次没有安装或启用 Linux 定时任务。

CLI Agent 应使用绝对路径；systemd 的凭据和 HOME 属于服务用户，不继承个人终端会话。单机本地磁盘运行，依赖 `fcntl`，未验证多机共享盘。旧 `.state/auth.sqlite3` 不再使用但不会自动删除；备份应覆盖所有数据根目录。暂未提供发布审批、告警或历史清理界面。

## 验证

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --check web/app.js
```

测试覆盖无登录公开读取、原始报告不开放、目录不存在拒收、未知成员、模板及编码校验、JSON/文件上传一致、同内容幂等、禁止覆盖、路径与符号链接、来源版本、输入变化、Agent 命令与失败保留旧总结。模型归纳的科研事实仍须核对原文。

## 已部署为资源中心模块

2026-10-19 已在 `rmp@101.132.97.146` 的 `/data/rmp/research-progress` 部署，挂到原资源中心 `/progress/`。沿用 SSH 隧道和紫色样式，Web 服务已启用，真实成员名单初始为空，模型及汇总定时器尚未配置。详见 [服务器部署记录](docs/server-deployment.md)。
