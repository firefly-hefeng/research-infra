# RMP-ELN-20261128-COMPACT-PROGRESS-VISUALIZATION

## 范围与设计

日期：2026-11-28，Asia/Shanghai。类型：界面工程验收与科研进度模块生产发布记录，不产生新的科研结论。

本轮只修改 `var/releases/integration-20261128/research-progress-next`，解决六类算法、重复方向索引和长方法卡片造成的信息分散，以及三级金字塔的嵌套卡片感。真实方向快照仍以只读方式核对，SHA-256 为 `0e3d99f6872165ca0b49b1667e4020286e4b36f9ce7137296b5cdfb0550016e7`；18 个方向、39 项方法及映射关系不变。

- 六个算法大类改为原生 `details/summary`。关闭时只显示类别、简述和方向/方法数；具体方向、稳定 ID 与算法名留在本卡展开区。首屏不再平铺 18 个方向和 39 项方法。
- 原“方向与专题”索引收进唯一总折叠卡，搜索框保持可见。服务端在 `q` 非空时输出 `open`，无查询时默认关闭；没有新增 JavaScript 或 API 字段。
- 方向详情的每项方法改为折叠条目。摘要只露出状态和名称，结果、指标、比较条件、适用范围及逐条证据完整保留在展开区，嵌套证据仍可独立展开。
- 复盘三级金字塔在同一容器内采用桌面三列渐进结构，移动端改为纵向。删除重复说明和内层卡片边框，保留三级计数、互链、四栏、引文、版本链接、键盘和打印规则。
- 缩短 intro、标题说明、卡片间距和索引行距；数量仍只描述覆盖，不形成跨量纲排名。

## 本地验证

- 集成副本 WSL 定向回归：`tests/test_direction_methods.py` 与 `tests/test_lab_review.py`，**30 passed**。新增断言覆盖六类原生折叠、唯一总索引、无查询关闭、查询自动展开、方法摘要与正文顺序、三级计数和互链。
- 使用真实 18 方向数据和既有复盘快照在 Chromium 中渲染首页、查询页、方向详情及复盘。首页初始为 6 张关闭卡片，18 个稳定 ID 和总方向索引不可见；键盘展开核心卡、总索引、方法及嵌套证据均通过。查询 `VoxMem` 时总索引自动展开且只剩匹配方向。
- 首页、详情和复盘在 1440 / 390 / 320 px 与 100% / 200% 根字号下均无水平溢出。复盘在 1440 px 实测三列同排且顺序递增，在 390 / 320 px 实测纵向排列；页内链接、键盘和打印检查通过。
- 已实际查看以下截图，确认首屏摘要密度、三列/纵向层级、长文本换行和卡片边界，未见遮挡或越界：
  - [方向首页 1440](evidence/2026-11-28-compact-direction-1440.png)
  - [方向首页 390](evidence/2026-11-28-compact-direction-390.png)
  - [三级复盘 1440](evidence/2026-11-28-compact-lab-1440.png)
  - [三级复盘 390](evidence/2026-11-28-compact-lab-390.png)
- 四组既有浏览器脚本最终全部通过：`check_archive_report.cjs`（1440 / 1057 / 390 / 320）、`check_report_views.cjs`、`check_progress_digest.cjs`、`check_session_recovery.cjs`（后三者均为 1440 / 390 / 320）。`check_report_views.cjs` 首次在 390 px 的空成员筛选计数处出现一次异步时序失败，未改业务代码，原脚本独立重跑后三种宽度全部通过。
- WSL 中曾下载隔离 Chromium，但系统缺少 `libasound.so.2`，无法启动；该临时浏览器负载已删除。上述四组脚本最终使用现有 Windows Chromium 和脚本自建的本地合成 HTTP 服务运行，未访问生产服务。

## WSL 全量 pytest

首次在高负载环境完整运行 179 项时为 **178 passed, 1 failed**，唯一失败是既有并发测试的三秒事件窗口超时。随后在负载恢复后先复跑该并发用例与本轮目标测试，得到 **31 passed**；再次完整运行全部测试，最终 **179 passed in 9.71s**。未修改并发逻辑或测试时限。

## 生产发布与回滚保护

发布目标仅为 `101.132.97.146:/data/rmp/research-progress/` 的两个 Python 展示模块和五个 Web 文件，未改配置、报告、数据库、成员原件、门户、文献或 MCP。

- 首次预检运行生产旧测试集，得到 52 passed、2 failed；失败均在既有 `tests/test_intake.py` 的收件行为/旧 mock 契约，不在本轮展示路径。目标文件立即恢复，生产服务未切换。
- 第二次预检发现生产仅含四份旧测试文件，没有新增目标测试路径，文件再次恢复并重启旧服务，回环页面保持 200。
- 最终把本轮三份目标测试放在独立 staging 中运行，生产虚拟环境实测 **34 passed**。随后仅重启 `research-weekly-web.service`，服务 active，`/direction-methods`、reviewed `/api/lab-review` 和 auto `/api/lab-review?format=json&version=auto` 均返回 200；六类折叠卡和三级金字塔标记核验通过。
- 成功备份：`/data/rmp/research-progress/var/release-backups/20261127T205753Z/`，含七个原文件、前后 SHA-256 清单和 `SUCCESS.json`。前两次预检备份也保留在同一父目录。
- 公网无登录复核：`/progress/direction-methods` 为 302 登录跳转，`/progress/api/lab-review` 为 401，统一门禁仍有效。真实浏览器到达飞书重新授权页，未代替成员点击授权；授权后的线上视觉复核留给成员检查。

## 边界

本轮未修改原工作区、冻结快照、JSON schema、API 或证据内容。截图和尺寸检查属于桌面 Chromium 视口与根字号模拟，不覆盖所有手机浏览器或辅助技术。WSL 浏览器系统库缺失不影响已完成的 Windows 浏览器回归；如需在纯 WSL 重跑仍需补齐 Chromium 动态库。生产旧收件测试的两项失配单独保留，未为追求全绿而修改无关业务。
