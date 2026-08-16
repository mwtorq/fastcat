<#
.SYNOPSIS
    Weekly AKC Fast CAT collection: find new events, import results, archive result HTML.

.DESCRIPTION
    Wraps the existing fastcat pipeline. New-result detection is built into
    scrape_and_import_fastcat.py, which skips any event that already has rows in
    sAKC.Results, so re-running over an overlapping date window is safe.

    sAKC.Results carries an AFTER INSERT/UPDATE/DELETE trigger that recalculates
    MPHAvg and Ranking for every row in the table on each statement. The import
    inserts one row at a time, so leaving the trigger on makes even a small import
    take days. The trigger ignores the inserted/deleted rows and just calls
    sp_UpdateMPHAvgAndRanking, so disabling it for the import and calling that
    procedure once afterwards produces identical values.

    Shared helpers live outside this repo because all three result-collection repos
    use them. Override the location with the RESULTS_AUTOMATION_HOME environment
    variable. Logs and run state are written there, not into this repo.

.EXAMPLE
    .\Run-FastCat.ps1
    .\Run-FastCat.ps1 -LookbackDays 120
    .\Run-FastCat.ps1 -StartDate 2026-01-01 -EndDate 2026-08-15
#>
[CmdletBinding()]
param(
    [string]$Python,
    [int]$LookbackDays = 45,
    [string]$StartDate,
    [string]$EndDate,
    [switch]$SkipHtmlArchive,
    [switch]$SkipRankingRecompute,
    [int]$RecomputeTimeoutSeconds = 21600,
    [switch]$DryRun
)

$AutomationHome = if ($env:RESULTS_AUTOMATION_HOME) { $env:RESULTS_AUTOMATION_HOME } else { 'C:\Users\mw\ResultsAutomation' }
$CommonPath     = Join-Path $AutomationHome 'Common.ps1'
if (-not (Test-Path -LiteralPath $CommonPath)) {
    throw "Shared helpers not found at $CommonPath. Set RESULTS_AUTOMATION_HOME to the folder holding Common.ps1."
}

. $CommonPath
$script:AutomationDryRun = [bool]$DryRun

$Repo     = Split-Path -Parent $PSScriptRoot
$Server   = 'localhost\SQLEXPRESS'
$Database = 'FastCAT'
$Trigger  = 'tr_Results_UpdateMPHAvgRanking'

Start-RunLog -Name 'fastcat' | Out-Null

try {
    $py = Resolve-PythonPath -Preferred $Python
    Write-Log "Python: $py"
    Write-Log "Repo:   $Repo"

    if (-not (Test-Path -LiteralPath (Join-Path $Repo 'scrape_and_import_fastcat.py'))) {
        throw "fastcat scripts not found under $Repo"
    }

    if (-not $EndDate)   { $EndDate   = (Get-Date).ToString('yyyy-MM-dd') }
    if (-not $StartDate) { $StartDate = (Get-Date).AddDays(-$LookbackDays).ToString('yyyy-MM-dd') }
    Write-Log "Scanning AKC event calendar from $StartDate through $EndDate"

    $eventsBefore  = Get-DbCount -Python $py -Server $Server -Database $Database -Query 'SELECT COUNT(*) FROM sAKC.Events'
    $resultsBefore = Get-DbCount -Python $py -Server $Server -Database $Database -Query 'SELECT COUNT(*) FROM sAKC.Results'
    Write-Log "Baseline: $eventsBefore events, $resultsBefore results"

    # A previous run that died between disable and re-enable leaves the trigger off.
    # Say so plainly rather than silently importing with rankings unmaintained.
    if ((Test-DbTriggerEnabled -Python $py -Server $Server -Database $Database -Trigger $Trigger) -eq $false) {
        Write-Log "Ranking trigger was already disabled before this run, so a previous run probably did not finish cleanly. It will be re-enabled at the end of this run." 'WARN'
    }

    if (-not (Invoke-DbStatement -Python $py -Server $Server -Database $Database -TimeoutSeconds 120 `
                -Statement "DISABLE TRIGGER sAKC.$Trigger ON sAKC.Results" `
                -Description 'Disabled per-row ranking trigger for the import')) {
        throw "Could not disable sAKC.$Trigger; refusing to import, because with it enabled each inserted row recomputes the whole table."
    }

    try {
        Invoke-Step -Name 'Scrape calendar and import new event results' `
            -Exe $py -WorkingDirectory $Repo `
            -Arguments @('scrape_and_import_fastcat.py', '--start', $StartDate, '--end', $EndDate) | Out-Null
    }
    finally {
        # Recompute while the trigger is still off: the procedure updates sAKC.Results
        # itself, which would otherwise re-fire the very trigger being replaced.
        $resultsAfterImport = Get-DbCount -Python $py -Server $Server -Database $Database -Query 'SELECT COUNT(*) FROM sAKC.Results'
        $newRows = if ($null -ne $resultsAfterImport -and $null -ne $resultsBefore) { $resultsAfterImport - $resultsBefore } else { $null }

        if ($SkipRankingRecompute) {
            Write-Log 'Skipping the MPHAvg/Ranking recompute by request; those columns are now stale.' 'WARN'
            Request-Attention 'Ranking recompute was skipped, so sAKC.Results MPHAvg and Ranking are stale. Run EXEC sAKC.sp_UpdateMPHAvgAndRanking when convenient.'
        }
        elseif ($newRows -eq 0) {
            Write-Log 'No new result rows, so no ranking recompute is needed.'
        }
        else {
            $howMany = if ($null -eq $newRows) { 'an unknown number of' } else { $newRows }
            Write-Log "Imported $howMany new result rows; recomputing MPHAvg and Ranking once for the whole table."
            if (-not (Invoke-DbStatement -Python $py -Server $Server -Database $Database -TimeoutSeconds $RecomputeTimeoutSeconds `
                        -Statement 'EXEC sAKC.sp_UpdateMPHAvgAndRanking' `
                        -Description 'Recomputed MPHAvg and Ranking')) {
                Request-Attention 'The MPHAvg/Ranking recompute failed, so those columns are stale for newly imported rows. Run EXEC sAKC.sp_UpdateMPHAvgAndRanking manually.'
            }
        }

        if (-not (Invoke-DbStatement -Python $py -Server $Server -Database $Database -TimeoutSeconds 120 `
                    -Statement "ENABLE TRIGGER sAKC.$Trigger ON sAKC.Results" `
                    -Description 'Re-enabled per-row ranking trigger')) {
            Request-Attention "sAKC.$Trigger is still DISABLED. Re-enable it with: ENABLE TRIGGER sAKC.$Trigger ON sAKC.Results"
        }
    }

    if (-not $SkipHtmlArchive) {
        Invoke-Step -Name 'Archive result HTML to AKCResults' `
            -Exe $py -WorkingDirectory $Repo `
            -Arguments @('download_akc_results.py') | Out-Null

        Invoke-Step -Name 'Backfill AKCDogID from archived HTML' `
            -Exe $py -WorkingDirectory $Repo `
            -Arguments @('update_akcdogid_from_html.py') | Out-Null
    }

    $eventsAfter  = Get-DbCount -Python $py -Server $Server -Database $Database -Query 'SELECT COUNT(*) FROM sAKC.Events'
    $resultsAfter = Get-DbCount -Python $py -Server $Server -Database $Database -Query 'SELECT COUNT(*) FROM sAKC.Results'
    Add-Metric -Label 'sAKC.Events'  -Before $eventsBefore  -After $eventsAfter
    Add-Metric -Label 'sAKC.Results' -Before $resultsBefore -After $resultsAfter
}
catch {
    Write-Log ("Unhandled error: {0}" -f $_.Exception.Message) 'ERROR'
    Write-Log ($_.ScriptStackTrace) 'ERROR'
    $script:CurrentRun.Steps.Add([pscustomobject]@{ Name = 'runner'; Status = 'FAILED'; ExitCode = 1; Seconds = 0 })
}

exit (Complete-RunLog)
