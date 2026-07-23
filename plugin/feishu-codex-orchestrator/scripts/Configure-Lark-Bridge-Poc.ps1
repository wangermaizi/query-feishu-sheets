param(
    [string]$ProfileName = "requirement-poc",
    [Parameter(Mandatory = $true)]
    [string]$DefaultWorkspace,
    [string]$BridgeConfig = (Join-Path $HOME ".lark-channel\config.json"),
    [string]$OrchestratorConfigDirectory = (Join-Path $HOME ".codex\feishu-requirement-orchestrator"),
    [switch]$AllowProductionBot,
    [switch]$Confirm
)

$ErrorActionPreference = "Stop"

if (-not $Confirm) {
    throw "Pass -Confirm before configuring the test profile"
}

$bridgeConfigPath = [System.IO.Path]::GetFullPath($BridgeConfig)
$orchestratorDirectory = [System.IO.Path]::GetFullPath($OrchestratorConfigDirectory)
$workspace = (Resolve-Path -LiteralPath $DefaultWorkspace).Path
$wrapper = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "bridge\codex-wrapper.cmd")).Path

function Read-Json([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing ${Label}: $Path"
    }
    return Get-Content -LiteralPath $Path -Encoding UTF8 -Raw | ConvertFrom-Json
}

function Ensure-ObjectProperty($Object, [string]$Name) {
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue ([pscustomobject]@{}) -Force
    }
    return $Object.PSObject.Properties[$Name].Value
}

$settingsPath = Join-Path $orchestratorDirectory "orchestrator.json"
$profilesPath = Join-Path $orchestratorDirectory "profiles.json"
$credentialsPath = Join-Path $orchestratorDirectory "credentials.json"
$settings = Read-Json $settingsPath "orchestrator.json"
$profiles = Read-Json $profilesPath "profiles.json"
$credentials = Read-Json $credentialsPath "credentials.json"
$bridge = Read-Json $bridgeConfigPath "Lark Bridge config"

$profileProperty = $bridge.profiles.PSObject.Properties[$ProfileName]
if ($null -eq $profileProperty) {
    throw "Bridge profile does not exist: $ProfileName. Complete QR initialization first."
}
$profile = $profileProperty.Value

$gatewayCredentialName = [string]$settings.gateway.credential
$gatewayCredential = $credentials.credentials.PSObject.Properties[$gatewayCredentialName].Value
$productionAppId = [string]$gatewayCredential.app_id
$testAppId = [string]$profile.accounts.app.appId
if ([string]::IsNullOrWhiteSpace($testAppId)) {
    $testAppId = [string]$profile.accounts.app.app_id
}
if ([string]::IsNullOrWhiteSpace($testAppId)) {
    $testAppId = [string]$profile.accounts.app.id
}
if ([string]::IsNullOrWhiteSpace($testAppId)) {
    throw "The test profile has no appId. Repeat Bridge initialization."
}
$productionAppReused = (
    -not [string]::IsNullOrWhiteSpace($productionAppId) -and
    $productionAppId -eq $testAppId
)
if ($productionAppReused -and -not $AllowProductionBot) {
    throw "The Bridge profile uses the production bot App ID. Pass -AllowProductionBot and stop FeishuCodexGateway before starting Bridge."
}

$allowedRepositories = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
if ($settings.default_repository) {
    [void]$allowedRepositories.Add([System.IO.Path]::GetFullPath([string]$settings.default_repository))
}
foreach ($route in @($settings.repository_routing.routes)) {
    if ($route.path) {
        [void]$allowedRepositories.Add([System.IO.Path]::GetFullPath([string]$route.path))
    }
}
foreach ($routeProperty in @($settings.gateway.profile_routes.PSObject.Properties)) {
    foreach ($repository in @($routeProperty.Value.repositories)) {
        if ($repository.path) {
            [void]$allowedRepositories.Add([System.IO.Path]::GetFullPath([string]$repository.path))
        }
    }
}
foreach ($savedProfile in @($profiles.profiles.PSObject.Properties.Value)) {
    if ($savedProfile.default_repository) {
        [void]$allowedRepositories.Add(
            [System.IO.Path]::GetFullPath([string]$savedProfile.default_repository)
        )
    }
    foreach ($repository in @($savedProfile.repositories)) {
        if ($repository.path) {
            [void]$allowedRepositories.Add([System.IO.Path]::GetFullPath([string]$repository.path))
        }
    }
}
if (-not $allowedRepositories.Contains([System.IO.Path]::GetFullPath($workspace))) {
    throw "Default workspace is not a repository registered in orchestrator: $workspace"
}

$codex = Ensure-ObjectProperty $profile "codex"
$codex | Add-Member -NotePropertyName "binaryPath" -NotePropertyValue $wrapper -Force
$codex | Add-Member -NotePropertyName "ignoreRules" -NotePropertyValue $false -Force
$codex | Add-Member -NotePropertyName "ignoreUserConfig" -NotePropertyValue $false -Force
$codex | Add-Member -NotePropertyName "inheritCodexHome" -NotePropertyValue $true -Force

$workspaces = Ensure-ObjectProperty $profile "workspaces"
$workspaces | Add-Member -NotePropertyName "default" -NotePropertyValue $workspace -Force

$permissions = Ensure-ObjectProperty $profile "permissions"
$permissions | Add-Member -NotePropertyName "defaultAccess" -NotePropertyValue "read-only" -Force
$permissions | Add-Member -NotePropertyName "maxAccess" -NotePropertyValue "workspace" -Force
$profile | Add-Member -NotePropertyName "sandbox" -NotePropertyValue ([pscustomobject]@{
        default = "read-only"
        max = "workspace-write"
        defaultMode = "read-only"
        maxMode = "workspace-write"
    }) -Force

$preferences = Ensure-ObjectProperty $profile "preferences"
$preferences | Add-Member -NotePropertyName "model" -NotePropertyValue "default" -Force

$access = Ensure-ObjectProperty $profile "access"
$allowedChats = @($settings.gateway.allowed_chat_ids | ForEach-Object { [string]$_ })
$admins = @($settings.gateway.admin_open_ids | ForEach-Object { [string]$_ })
$access | Add-Member -NotePropertyName "allowedChats" -NotePropertyValue $allowedChats -Force
$access | Add-Member -NotePropertyName "admins" -NotePropertyValue $admins -Force
$access | Add-Member -NotePropertyName "requireMentionInGroup" -NotePropertyValue (
    $settings.gateway.require_group_mention -ne $false
) -Force

$backup = "$bridgeConfigPath.backup-$(Get-Date -Format 'yyyyMMddHHmmss')"
Copy-Item -LiteralPath $bridgeConfigPath -Destination $backup
$temporary = "$bridgeConfigPath.$PID.tmp"
$json = $bridge | ConvertTo-Json -Depth 30
[System.IO.File]::WriteAllText($temporary, "$json`n", [System.Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temporary -Destination $bridgeConfigPath -Force

[pscustomobject]@{
    configured = $true
    profile = $ProfileName
    workspace = $workspace
    wrapper = $wrapper
    default_access = "read-only"
    max_access = "workspace"
    production_app_reused = $productionAppReused
    requires_gateway_handoff = $productionAppReused
    allowed_chat_count = $allowedChats.Count
    admin_count = $admins.Count
    sender_scoped_sessions = $true
    backup = $backup
} | ConvertTo-Json
