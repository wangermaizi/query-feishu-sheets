param(
    [string]$ConfigDirectory = (Join-Path $HOME ".codex\feishu-requirement-orchestrator"),
    [string]$TaskName = "FeishuCodexGateway",
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"

$pluginRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gatewayDirectory = Join-Path $pluginRoot "scripts\gateway"
$node = (Get-Command node -ErrorAction Stop).Source
$npm = (Get-Command npm -ErrorAction Stop).Source
$nodeMajor = [int]((& $node --version).TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 22) {
    throw "FeishuCodexGateway requires Node.js 22 or later"
}

Push-Location $gatewayDirectory
try {
    & $npm ci --omit=dev --omit=optional
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    $env:FEISHU_ORCHESTRATOR_CONFIG_DIR = $ConfigDirectory
    & $node "src\cli.js" validate | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Gateway configuration validation failed" }
}
finally {
    Pop-Location
}

function Quote-Argument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

$arguments = @(
    (Quote-Argument "src\main.js"),
    "--config-dir", (Quote-Argument (Resolve-Path $ConfigDirectory).Path)
) -join " "

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $node -Argument $arguments -WorkingDirectory $gatewayDirectory
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null

if (-not $NoStart) {
    Start-ScheduledTask -TaskName $TaskName
}

[pscustomobject]@{
    installed = $true
    task_name = $TaskName
    user = $currentUser
    config_directory = (Resolve-Path $ConfigDirectory).Path
    gateway_directory = $gatewayDirectory
    started = -not $NoStart
} | ConvertTo-Json
