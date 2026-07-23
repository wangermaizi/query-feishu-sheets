$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pluginName = "feishu-codex-orchestrator"
$skillName = "feishu-requirement-orchestrator"
$pluginSource = Join-Path $root "plugin\$pluginName"
$skillSource = Join-Path $pluginSource "skills\$skillName"
$gateway = Join-Path $pluginSource "scripts\gateway"
$dist = Join-Path $root "dist"
$pluginStage = Join-Path $dist $pluginName
$skillStage = Join-Path $dist $skillName
$pluginArchive = Join-Path $dist "$pluginName.zip"
$skillArchive = Join-Path $dist "$skillName.zip"
$pluginChecksum = Join-Path $dist "$pluginName.sha256"
$skillChecksum = Join-Path $dist "$skillName.sha256"
$skillValidator = Join-Path $root "scripts\validate_skill.py"
$pluginValidator = Join-Path $root "scripts\validate_plugin.py"

if (-not $dist.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use a dist path outside the repository"
}

uv run pytest
if ($LASTEXITCODE -ne 0) { throw "Python tests failed" }

Push-Location $gateway
try {
    npm ci --omit=optional
    if ($LASTEXITCODE -ne 0) { throw "Gateway dependency installation failed" }
    npm run check
    if ($LASTEXITCODE -ne 0) { throw "Gateway source validation failed" }
    npm test
    if ($LASTEXITCODE -ne 0) { throw "Gateway tests failed" }
    npm audit --audit-level=moderate
    if ($LASTEXITCODE -ne 0) { throw "Gateway dependency audit failed" }
}
finally {
    Pop-Location
}

$env:PYTHONUTF8 = "1"
uv run $skillValidator $skillSource
if ($LASTEXITCODE -ne 0) { throw "Distributable Skill validation failed" }
uv run $pluginValidator $pluginSource
if ($LASTEXITCODE -ne 0) { throw "Distributable Plugin validation failed" }

$repoSkills = Join-Path $root ".agents\skills"
if (Test-Path -LiteralPath $repoSkills) {
    Get-ChildItem -LiteralPath $repoSkills -Directory | ForEach-Object {
        uv run $skillValidator $_.FullName
        if ($LASTEXITCODE -ne 0) {
            throw "Repository Skill validation failed: $($_.FullName)"
        }
    }
}

if (Test-Path -LiteralPath $dist) {
    $resolvedDist = (Resolve-Path -LiteralPath $dist).Path
    if (-not $resolvedDist.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a dist path outside the repository"
    }
    Remove-Item -LiteralPath $resolvedDist -Recurse -Force
}
New-Item -ItemType Directory -Path $dist | Out-Null
Copy-Item -LiteralPath $pluginSource -Destination $pluginStage -Recurse
Copy-Item -LiteralPath $skillSource -Destination $skillStage -Recurse

Get-ChildItem -LiteralPath $pluginStage -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $skillStage -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force
$gatewayTests = Join-Path $pluginStage "scripts\gateway\test"
if (Test-Path -LiteralPath $gatewayTests) {
    Remove-Item -LiteralPath $gatewayTests -Recurse -Force
}

$forbiddenFiles = @(
    "credentials.json",
    "profiles.json",
    "orchestrator.json",
    "state.json",
    "gateway-state.json",
    "gateway-status.json",
    "gateway.log"
)
Get-ChildItem -LiteralPath $pluginStage -Recurse -File |
    Where-Object { $_.Name -in $forbiddenFiles } |
    ForEach-Object { throw "Sensitive runtime file found in artifact: $($_.FullName)" }

uv run $skillValidator (Join-Path $pluginStage "skills\$skillName")
if ($LASTEXITCODE -ne 0) { throw "Staged Skill validation failed" }
uv run $pluginValidator $pluginStage
if ($LASTEXITCODE -ne 0) { throw "Staged Plugin validation failed" }

Compress-Archive -LiteralPath $skillStage -DestinationPath $skillArchive -CompressionLevel Optimal
Compress-Archive -LiteralPath $pluginStage -DestinationPath $pluginArchive -CompressionLevel Optimal

$skillHash = (Get-FileHash -LiteralPath $skillArchive -Algorithm SHA256).Hash.ToLowerInvariant()
$pluginHash = (Get-FileHash -LiteralPath $pluginArchive -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $skillChecksum -Value "$skillHash  $skillName.zip" -Encoding ascii
Set-Content -LiteralPath $pluginChecksum -Value "$pluginHash  $pluginName.zip" -Encoding ascii

Write-Output "Built Skill: $skillArchive"
Write-Output "Skill SHA256: $skillHash"
Write-Output "Built Plugin: $pluginArchive"
Write-Output "Plugin SHA256: $pluginHash"
