# Backup trigger: starts the publisher on GitHub if no run is active or waiting.
# Run by a Windows scheduled task every 10 minutes while this PC is on.
$gh = "C:\Program Files\GitHub CLI\gh.exe"
$repo = "iqbal-jewel/german-shepherd-publisher"
$active = & $gh run list --repo $repo --workflow auto_publish.yml --limit 10 --json status --jq '[.[] | select(.status=="in_progress" or .status=="queued" or .status=="waiting" or .status=="pending")] | length' 2>$null
if ($LASTEXITCODE -eq 0 -and "$active" -eq "0") {
    & $gh workflow run auto_publish.yml --repo $repo --ref main | Out-Null
    "$(Get-Date -Format s) started a new run" | Add-Content "$PSScriptRoot\keepalive.log"
}
