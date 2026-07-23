param(
    [string]$ConfigDirectory = (Join-Path $HOME ".codex\feishu-requirement-orchestrator"),
    [string]$TaskName = "FeishuCodexGateway"
)

$ErrorActionPreference = "Stop"

$pluginRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatewayDirectory = Join-Path $pluginRoot "scripts\gateway"
$node = (Get-Command node -ErrorAction Stop).Source
$scheduledTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$taskInfo = if ($scheduledTask) { Get-ScheduledTaskInfo -TaskName $TaskName } else { $null }
$env:FEISHU_ORCHESTRATOR_CONFIG_DIR = $ConfigDirectory

Push-Location $gatewayDirectory
try {
    $gateway = & $node "src\cli.js" status | ConvertFrom-Json
}
finally {
    Pop-Location
}

[pscustomobject]@{
    installed = $null -ne $scheduledTask
    scheduled_state = if ($scheduledTask) { [string]$scheduledTask.State } else { "NotInstalled" }
    last_run_time = if ($taskInfo) { $taskInfo.LastRunTime } else { $null }
    last_task_result = if ($taskInfo) { $taskInfo.LastTaskResult } else { $null }
    gateway = $gateway
} | ConvertTo-Json -Depth 6
