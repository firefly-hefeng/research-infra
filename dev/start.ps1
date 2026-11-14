$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path $pythonPath)) { throw '请先建立 .venv 并安装 dev/README.md 中的依赖。' }
New-Item -ItemType Directory -Force (Join-Path $projectRoot '.local-dev') | Out-Null
$runner = Join-Path $PSScriptRoot 'run.py'
$process = Start-Process -FilePath $pythonPath -ArgumentList @('-u', ('"' + $runner + '"')) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot '.local-dev/gateway.log') -RedirectStandardError (Join-Path $projectRoot '.local-dev/gateway-error.log')
Write-Output "启动进程 $($process.Id)，访问 http://127.0.0.1:18081/；如启动失败，请查看 .local-dev 日志。"
