param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^v\d+\.\d+\.\d+$')]
    [string]$Tag,

    [ValidateRange(1, 300)]
    [int]$TimeoutSeconds = 60,

    [ValidateRange(1, 30)]
    [int]$PollIntervalSeconds = 5
)

$ErrorActionPreference = "Stop"
$deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)

while ($true) {
    $json = gh run list `
        --workflow "build-skill.yml" `
        --branch $Tag `
        --event push `
        --limit 10 `
        --json databaseId,status,conclusion,url,headBranch,headSha,createdAt

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to query GitHub Actions runs."
    }

    $runs = @($json | ConvertFrom-Json)
    $run = $runs |
        Where-Object { $_.headBranch -eq $Tag } |
        Sort-Object createdAt -Descending |
        Select-Object -First 1

    if ($null -ne $run) {
        [pscustomobject]@{
            tag = $Tag
            run_id = $run.databaseId
            status = $run.status
            url = $run.url
            head_sha = $run.headSha
            detected_at = [DateTimeOffset]::Now.ToString("o")
        } | ConvertTo-Json
        exit 0
    }

    if ([DateTimeOffset]::UtcNow -ge $deadline) {
        throw "No Build Skill workflow run was detected for $Tag within $TimeoutSeconds seconds."
    }

    Start-Sleep -Seconds $PollIntervalSeconds
}
