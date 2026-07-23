param(
    [string]$Version = "0.6.0"
)

$ErrorActionPreference = "Stop"

npm install --global "lark-channel-bridge@$Version" --registry "https://registry.npmjs.org"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install lark-channel-bridge"
}

$command = Get-Command "lark-channel-bridge" -ErrorAction Stop
$reportedVersion = & $command.Source --version
if ($LASTEXITCODE -ne 0) {
    throw "lark-channel-bridge cannot run"
}

$patchResult = & (Join-Path $PSScriptRoot "Patch-Lark-Bridge-Poc.ps1") -Version $Version |
    ConvertFrom-Json

[pscustomobject]@{
    installed = $true
    requested_version = $Version
    reported_version = [string]$reportedVersion
    command = $command.Source
    sender_scope_patch = $patchResult
    next_command = "lark-channel-bridge run --profile requirement-poc --agent codex"
} | ConvertTo-Json
