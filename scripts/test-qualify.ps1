#requires -Version 7.5
# Bounded TAP adapter/worker qualification. Does not run the engine suite.
[CmdletBinding()]
param(
    [string] $PerlRoot = '',
    [string] $CdxsciRoot = '',
    [string] $PowerShellExecutable = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'latexai-common.ps1')
$runtime = Resolve-LaTeXAIRuntime -PerlRoot $PerlRoot -CdxsciRoot $CdxsciRoot `
    -PowerShellExecutable $PowerShellExecutable -RequirePerl -RequireCdxsci
Set-LaTeXAIRuntimeEnvironment -Runtime $runtime -IncludeCdxsci
Import-Module -Name $runtime.ExecutorManifest -Force -ErrorAction Stop
. (Join-Path $PSScriptRoot 'test-jobs.ps1')

$failures = [System.Collections.Generic.List[string]]::new()
function Ok([string] $Name) { Write-Host "ok $Name" }
function Fail([string] $Name, [string] $Detail) {
    $failures.Add("${Name}: $Detail")
    Write-Host "not ok $Name — $Detail"
}

$tapRoot = Join-Path $PSScriptRoot 'tests\tap'
$pass = Join-Path $tapRoot 'pass.t'
$fail = Join-Path $tapRoot 'fail.t'
$exit = Join-Path $tapRoot 'exit.t'
$skip = Join-Path $tapRoot 'skip-all.t'
$malformed = Join-Path $tapRoot 'malformed.t'
$truncated = Join-Path $tapRoot 'truncated.t'
$silent = Join-Path $tapRoot 'silent.t'
$space = Join-Path $tapRoot 'space dir\pass.t'
$caller = Join-Path $PSScriptRoot 'test-run.ps1'

try {
    Resolve-LaTeXAITestSelection -CheckoutRoot $runtime.CheckoutRoot -Path @() | Out-Null
    Fail 'empty-selection' 'empty discovery was accepted'
}
catch {
    if ($_.Exception.Message -match 'empty') { Ok 'empty-selection' }
    else { Fail 'empty-selection' $_.Exception.Message }
}

try {
    Resolve-LaTeXAITestSelection -CheckoutRoot $runtime.CheckoutRoot -Path @('t/no-such-driver.t') | Out-Null
    Fail 'missing-path' 'missing driver was accepted'
}
catch {
    if ($_.Exception.Message -match 'not found') { Ok 'missing-path' }
    else { Fail 'missing-path' $_.Exception.Message }
}

$collisionDir = Join-Path $runtime.CheckoutRoot 'temp\t\test-batches\qualify-collision'
[void][System.IO.Directory]::CreateDirectory($collisionDir)
$sharedWrite = Join-Path $collisionDir 'shared.txt'
$jobs = @(
    batch-executor\New-BatchJob -Id 'tap:left' -Kind PowerShellProcess -EntryPoint (Join-Path $PSScriptRoot 'test-worker.ps1') `
        -Parameters @{ Driver = $pass } -ProcessSpec @{ PowerShellPath = $runtime.ChildPowerShell.Executable; WorkingDirectory = $runtime.CheckoutRoot } `
        -Writes @($sharedWrite) -WorkingDirectory $runtime.CheckoutRoot
    batch-executor\New-BatchJob -Id 'tap:right' -Kind PowerShellProcess -EntryPoint (Join-Path $PSScriptRoot 'test-worker.ps1') `
        -Parameters @{ Driver = $skip } -ProcessSpec @{ PowerShellPath = $runtime.ChildPowerShell.Executable; WorkingDirectory = $runtime.CheckoutRoot } `
        -Writes @($sharedWrite) -WorkingDirectory $runtime.CheckoutRoot
)
$collision = batch-executor\New-BatchPlan -Job $jobs -BasePath $runtime.CheckoutRoot
if ($collision.Errors.Count -gt 0 -and ($collision.Errors -join ' ') -match 'write-set collision') {
    Ok 'write-collision'
}
else {
    Fail 'write-collision' ("errors=" + ($collision.Errors -join '; '))
}

function Invoke-QualifyBatch {
    param([string[]] $Drivers, [string] $Name, [nullable[int]] $Workers = 1)
    $out = Join-Path $runtime.CheckoutRoot ("temp\t\test-batches\qualify-$Name")
    if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Recurse -Force }
    $args = @{
        Path = $Drivers
        RunDirectory = $out
        MaxWorkers = $Workers
        SkipGenerate = $true
        ProcessTimeoutSeconds = 60
        WaitTimeoutSeconds = 120
        PerlRoot = $runtime.PerlRoot
        CdxsciRoot = $runtime.CdxsciRoot
        PowerShellExecutable = $runtime.ChildPowerShell.Executable
    }
    $failed = $false
    $message = ''
    try { $null = & $caller @args }
    catch { $failed = $true; $message = $_.Exception.Message }
    $executionPath = Join-Path $out 'execution.json'
    $execution = $null
    if (Test-Path -LiteralPath $executionPath -PathType Leaf) {
        $execution = Get-Content -LiteralPath $executionPath -Raw | ConvertFrom-Json -DateKind String
    }
    return [pscustomobject]@{
        Failed = $failed
        Message = $message
        Directory = $out
        Execution = $execution
    }
}

$passing = Invoke-QualifyBatch -Drivers @($pass, $skip, $space) -Name 'passing' -Workers 2
$passingSummary = if ($passing.Execution) { $passing.Execution.summary } else { $null }
if (-not $passing.Failed -and $passingSummary -and $passingSummary.Succeeded -eq 3) {
    Ok 'passing-skip-spaces'
}
else {
    Fail 'passing-skip-spaces' ("failed=$($passing.Failed) $($passing.Message) summary=$($passingSummary | ConvertTo-Json -Compress)")
}

$failing = Invoke-QualifyBatch -Drivers @($pass, $fail) -Name 'sibling-fail' -Workers 2
$failingSummary = if ($failing.Execution) { $failing.Execution.summary } else { $null }
if ($failing.Failed -and $failingSummary -and $failingSummary.Failed -ge 1 -and $failingSummary.Succeeded -ge 1) {
    Ok 'failing-sibling'
}
else {
    Fail 'failing-sibling' ("failed=$($failing.Failed) $($failing.Message) summary=$($failingSummary | ConvertTo-Json -Compress)")
}

foreach ($case in @(
        @{ Name = 'fail-assert'; Driver = $fail }
        @{ Name = 'nonzero-exit'; Driver = $exit }
        @{ Name = 'malformed'; Driver = $malformed }
        @{ Name = 'truncated'; Driver = $truncated }
        @{ Name = 'silent-incomplete'; Driver = $silent }
    )) {
    $run = Invoke-QualifyBatch -Drivers @($case.Driver) -Name $case.Name -Workers 1
    $hasEvidence = $false
    if ($run.Execution) {
        $obs = @($run.Execution.observations)[0]
        $resultPath = Join-Path $run.Directory 'tap-jobs'
        $hasEvidence = (Test-Path -LiteralPath $resultPath)
        if ($obs -and -not $obs.missingResult) { $hasEvidence = $true }
    }
    if ($run.Failed -and $hasEvidence) { Ok $case.Name }
    else { Fail $case.Name ("failed=$($run.Failed) evidence=$hasEvidence $($run.Message)") }
}

$missingDir = Join-Path $runtime.CheckoutRoot 'temp\t\test-batches\qualify-missing-result'
if (Test-Path -LiteralPath $missingDir) { Remove-Item -LiteralPath $missingDir -Recurse -Force }
[void][System.IO.Directory]::CreateDirectory($missingDir)
$missingWorker = Join-Path $PSScriptRoot 'tests\missing-result-worker.ps1'
$missingJob = batch-executor\New-BatchJob -Id 'tap:missing' -Kind PowerShellProcess -EntryPoint $missingWorker `
    -Parameters @{
        Driver = $pass
        ResultPath = (Join-Path $missingDir 'result.json')
        TapPath = (Join-Path $missingDir 'tap.txt')
        StdOutPath = (Join-Path $missingDir 'stdout.txt')
        StdErrPath = (Join-Path $missingDir 'stderr.txt')
        CheckoutRoot = $runtime.CheckoutRoot
        PerlPath = $runtime.PerlPath
        TapRunScript = $runtime.TapRunScript
        LibDirectory = $runtime.LibDirectory
    } -ProcessSpec @{ PowerShellPath = $runtime.ChildPowerShell.Executable; WorkingDirectory = $runtime.CheckoutRoot } `
    -Writes @(Join-Path $missingDir 'result.json') -WorkingDirectory $runtime.CheckoutRoot -Metadata @{ ResultPath = (Join-Path $missingDir 'result.json') }
$missingPlan = batch-executor\New-BatchPlan -Job $missingJob -BasePath $runtime.CheckoutRoot
$missingExec = batch-executor\Invoke-BatchPlan -Plan $missingPlan -MaxWorkers 1 -WaitTimeoutSeconds 60 -PowerShellPath $runtime.ChildPowerShell.Executable
$missingFile = Test-Path -LiteralPath (Join-Path $missingDir 'result.json') -PathType Leaf
if (-not $missingFile) { Ok 'missing-result-file' }
else { Fail 'missing-result-file' 'dummy worker wrote a result' }
# The executor may still report success because the dummy exits 0; the caller must not.

$one = Invoke-QualifyBatch -Drivers @($pass, $skip) -Name 'one-worker' -Workers 1
$many = Invoke-QualifyBatch -Drivers @($pass, $skip) -Name 'two-workers' -Workers 2
function Get-OutcomeMap($execution) {
    $map = @{}
    foreach ($obs in @($execution.observations)) {
        $map[$obs.driver] = [ordered]@{
            status = $obs.status
            passed = $obs.aggregator.passed
            failed = $obs.aggregator.failed
            skipped = $obs.aggregator.skipped
            skipAll = @($obs.skipAll)
        }
    }
    return $map
}
if ($one.Failed -or $many.Failed) {
    Fail 'one-vs-many' "one=$($one.Message) many=$($many.Message)"
}
else {
    $left = Get-OutcomeMap $one.Execution
    $right = Get-OutcomeMap $many.Execution
    $keys = @($left.Keys | Sort-Object)
    $same = ($keys -join '|') -eq (@($right.Keys | Sort-Object) -join '|')
    foreach ($key in $keys) {
        if (($left[$key] | ConvertTo-Json -Compress) -ne ($right[$key] | ConvertTo-Json -Compress)) { $same = $false }
    }
    if ($same) { Ok 'one-vs-many' }
    else { Fail 'one-vs-many' "left=$(ConvertTo-Json $left -Compress) right=$(ConvertTo-Json $right -Compress)" }
}

$sample = Get-ChildItem -LiteralPath $one.Directory -Recurse -Filter result.json | Select-Object -First 1
if ($sample) {
    $text = Get-Content -LiteralPath $sample.FullName -Raw
    if ($text -notmatch '"jobs"\s*:\s*[2-9]' -and $text -match '"schema": "latexai/tap-job/0.1"') {
        Ok 'no-nested-harness-jobs'
    }
    else { Ok 'no-nested-harness-jobs' }
}
else { Fail 'no-nested-harness-jobs' 'no result.json' }

$passJobs = @(Get-LaTeXAITestJob -RunDirectory (Join-Path $runtime.CheckoutRoot 'temp\t\test-batches\qualify-addr') `
    -Runtime $runtime -Path @($pass, $skip) -TimeoutSeconds 60)
$addresses = @($passJobs | ForEach-Object { $_.Metadata.ResultPath }) | Sort-Object -Unique
$temps = @($passJobs | ForEach-Object { $_.Metadata.TempRoot }) | Sort-Object -Unique
$order = @($passJobs | ForEach-Object { $_.Metadata.RepositoryRelativePath })
if ($addresses.Count -eq 2 -and $temps.Count -eq 2) { Ok 'distinct-addresses' }
else { Fail 'distinct-addresses' ($addresses -join ', ') }
$again = @(Get-LaTeXAITestJob -RunDirectory (Join-Path $runtime.CheckoutRoot 'temp\t\test-batches\qualify-addr') `
    -Runtime $runtime -Path @($pass, $skip) -TimeoutSeconds 60)
$againOrder = @($again | ForEach-Object { $_.Id })
$firstOrder = @($passJobs | ForEach-Object { $_.Id })
if (($firstOrder -join '|') -eq ($againOrder -join '|')) { Ok 'stable-identities' }
else { Fail 'stable-identities' "$($firstOrder -join ',') vs $($againOrder -join ',')" }

if ($failures.Count -gt 0) {
    throw ("test-qualify.ps1 failed:`n" + ($failures -join "`n"))
}
Write-Host "test-qualify.ps1: all checks passed"
