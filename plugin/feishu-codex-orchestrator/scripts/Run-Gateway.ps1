param(
    [Parameter(Mandatory = $true)]
    [string]$GatewayDirectory,
    [Parameter(Mandatory = $true)]
    [string]$NodePath,
    [string]$ConfigDirectory
)

$ErrorActionPreference = "Stop"

if ($ConfigDirectory) {
    $env:FEISHU_ORCHESTRATOR_CONFIG_DIR = $ConfigDirectory
}
Set-Location -LiteralPath $GatewayDirectory
& $NodePath "src\main.js"
exit $LASTEXITCODE
