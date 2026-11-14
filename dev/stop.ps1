$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$recordPath = Join-Path $projectRoot '.local-dev/processes.json'
if (-not (Test-Path $recordPath)) { Write-Output '没有本地开发进程记录。'; exit 0 }
$record = Get-Content -Raw $recordPath | ConvertFrom-Json
$runner = Join-Path $PSScriptRoot 'run.py'
foreach ($taskProcessId in @($record.modules) + @($record.gateway)) {
    $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $taskProcessId"
    if ($taskProcess -and $taskProcess.CommandLine -and $taskProcess.CommandLine.IndexOf($runner, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        Stop-Process -Id $taskProcessId
        Write-Output "已停止本地开发进程 $taskProcessId"
    }
}
