$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$skillName = "feishu-requirement-orchestrator"
$source = Join-Path $root "skill\$skillName"
$dist = Join-Path $root "dist"
$stage = Join-Path $dist $skillName
$archive = Join-Path $dist "$skillName.zip"
$checksum = Join-Path $dist "$skillName.sha256"
$validator = Join-Path $root "scripts\validate_skill.py"

if (-not $dist.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use a dist path outside the repository"
}

uv run pytest
$env:PYTHONUTF8 = "1"
uv run $validator $source
$repoSkills = Join-Path $root ".agents\skills"
if (Test-Path -LiteralPath $repoSkills) {
    Get-ChildItem -LiteralPath $repoSkills -Directory | ForEach-Object {
        uv run $validator $_.FullName
    }
}

if (Test-Path -LiteralPath $dist) {
    Remove-Item -LiteralPath $dist -Recurse -Force
}
New-Item -ItemType Directory -Path $dist | Out-Null
Copy-Item -LiteralPath $source -Destination $stage -Recurse

Get-ChildItem -LiteralPath $stage -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $stage -Recurse -File |
    Where-Object { $_.Name -in @("credentials.json", "profiles.json", "orchestrator.json", "state.json") } |
    ForEach-Object { throw "Sensitive runtime file found in artifact: $($_.FullName)" }

Compress-Archive -LiteralPath $stage -DestinationPath $archive -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $checksum -Value "$hash  $skillName.zip" -Encoding ascii
Write-Output "Built: $stage"
Write-Output "Built: $archive"
Write-Output "SHA256: $hash"
