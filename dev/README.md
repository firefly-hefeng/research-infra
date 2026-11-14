# 本地页面开发

在仓库根目录运行（Windows / Python 3.11）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r research-progress-next/requirements.lock.txt tzdata
powershell -ExecutionPolicy Bypass -File dev/start.ps1
```

统一入口 http://127.0.0.1:18081/；进度 `/progress/`；文献 `/papers/`。只监听本机，无线上飞书登录，也不连接生产数据。模块端口 8765、8766、4186 必须空闲。

页面直接读取 `research-data-center-next/static/`、`research-progress-next/web/` 和 `paper-library-next/web/`；HTML/CSS/JS 修改后刷新即可，Python 修改需要重启进程。仓库与线上版本存在差异，本地不是生产服务器的完整镜像。

`.local-dev/` 保存本地目录数据库、演示成员、报告、空论文库与日志，不纳入 Git。资源和算力页面展示仓库自带的元数据快照，不是实时监控。未连接模型服务或自动调度。论文 PDF 文本提取仍需要自行安装 Poppler；空库页面预览不需要。

`windows_locks.py` 仅由本地启动器注入到 Windows 子进程，使用真正的 Windows 文件锁。周报的原子写入显式保留 LF 换行，避免 Windows 转换为 CRLF 后重复提交误报冲突；Linux 行为不变。Linux 共享数据入库及冷备任务不在本地启动。

停止：`powershell -ExecutionPolicy Bypass -File dev/stop.ps1`（会核对进程命令后再停止）。重启先停止再启动。也可以前台运行 `.venv/Scripts/python.exe dev/run.py`，使用 Ctrl+C 统一停止。
