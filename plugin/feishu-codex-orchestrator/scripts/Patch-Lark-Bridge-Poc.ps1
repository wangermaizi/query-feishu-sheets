param(
    [string]$Version = "0.6.0"
)

$ErrorActionPreference = "Stop"

$command = Get-Command "lark-channel-bridge" -ErrorAction Stop
$reportedVersion = [string](& $command.Source --version)
if ($LASTEXITCODE -ne 0 -or $reportedVersion.Trim() -ne $Version) {
    throw "Sender-scoped patch only supports lark-channel-bridge $Version; installed: $reportedVersion"
}

$npmRoot = [string](& npm root --global)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($npmRoot)) {
    throw "Cannot locate the global npm module directory"
}
$target = Join-Path $npmRoot.Trim() "lark-channel-bridge\dist\cli.js"
$patcher = Join-Path $PSScriptRoot "bridge\patch-user-scope.mjs"
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
    throw "Missing lark-channel-bridge CLI bundle: $target"
}

$result = & node $patcher $target
if ($LASTEXITCODE -ne 0) {
    throw "Failed to apply sender-scoped Bridge patch"
}
$result | ConvertFrom-Json | Add-Member -NotePropertyName version -NotePropertyValue $Version -PassThru |
    ConvertTo-Json
