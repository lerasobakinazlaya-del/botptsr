param(
    [string]$Repo = "lerasobakinazlaya-del/botptsr",
    [string]$Workflow = "deploy.yml",
    [string]$Branch = "",
    [string]$AppDir = "/opt/bot",
    [switch]$Wait,
    [int]$PollSeconds = 5,
    [int]$TimeoutSeconds = 600
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-GitHubToken {
    if ($env:GH_TOKEN) {
        return $env:GH_TOKEN
    }

    if ($env:GITHUB_TOKEN) {
        return $env:GITHUB_TOKEN
    }

    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($gh) {
        try {
            $token = (& $gh.Source auth token 2>$null).Trim()
            if ($token) {
                return $token
            }
        }
        catch {
        }
    }

    $gcm = "C:\Program Files\Git\mingw64\bin\git-credential-manager.exe"
    if (Test-Path $gcm) {
        $raw = "protocol=https`nhost=github.com`n`n" | & $gcm get
        if ($raw) {
            $credential = @{}
            foreach ($line in $raw) {
                if ($line -match "^(.*?)=(.*)$") {
                    $credential[$matches[1]] = $matches[2]
                }
            }

            if ($credential.ContainsKey("password") -and $credential["password"]) {
                return $credential["password"]
            }
        }
    }

    throw "GitHub token not found. Set GH_TOKEN/GITHUB_TOKEN, login via gh, or store credentials in Git Credential Manager."
}

function Get-CurrentBranch {
    $resolved = (& git rev-parse --abbrev-ref HEAD).Trim()
    if (-not $resolved) {
        throw "Could not determine current git branch."
    }
    return $resolved
}

if (-not $Branch) {
    $Branch = Get-CurrentBranch
}

$token = Get-GitHubToken
$headers = @{
    Authorization = "Bearer $token"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

$dispatchBody = @{
    ref = $Branch
    inputs = @{
        branch = $Branch
        app_dir = $AppDir
    }
} | ConvertTo-Json -Depth 5

$workflowEncoded = [uri]::EscapeDataString($Workflow)
$branchEncoded = [uri]::EscapeDataString($Branch)
$dispatchUri = "https://api.github.com/repos/$Repo/actions/workflows/$workflowEncoded/dispatches"
$runsUri = "https://api.github.com/repos/$Repo/actions/workflows/$workflowEncoded/runs?event=workflow_dispatch&branch=$branchEncoded&per_page=10"

$startedAt = Get-Date
Invoke-WebRequest -Method POST -Uri $dispatchUri -Headers $headers -Body $dispatchBody -ContentType "application/json" | Out-Null
Start-Sleep -Seconds 3

$runs = Invoke-RestMethod -Method GET -Uri $runsUri -Headers $headers
$run = $runs.workflow_runs |
    Where-Object { [datetime]$_.created_at -ge $startedAt.AddMinutes(-1) } |
    Sort-Object created_at -Descending |
    Select-Object -First 1

if (-not $run) {
    throw "Workflow dispatch succeeded, but the matching run was not found yet."
}

Write-Host "Workflow started:"
Write-Host "  Name: $($run.name)"
Write-Host "  Id: $($run.id)"
Write-Host "  Status: $($run.status)"
Write-Host "  Url: $($run.html_url)"

if (-not $Wait) {
    return
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    Start-Sleep -Seconds $PollSeconds
    $run = Invoke-RestMethod -Method GET -Uri "https://api.github.com/repos/$Repo/actions/runs/$($run.id)" -Headers $headers
    Write-Host "Current status: $($run.status)"
} while ($run.status -in @("queued", "in_progress", "waiting") -and (Get-Date) -lt $deadline)

Write-Host "Final status: $($run.status)"
Write-Host "Conclusion: $($run.conclusion)"
Write-Host "Run URL: $($run.html_url)"

if ($run.status -ne "completed") {
    throw "Timed out while waiting for workflow completion."
}

if ($run.conclusion -ne "success") {
    throw "Workflow completed with conclusion '$($run.conclusion)'."
}
