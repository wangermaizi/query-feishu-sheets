param(
    [string]$TaskName = "FeishuCodexGateway"
)

$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

[pscustomobject]@{
    uninstalled = $true
    task_name = $TaskName
    runtime_configuration_preserved = $true
} | ConvertTo-Json
