#requires -Version 7.5
<#
  scripts/test-run.ps1 — TAP batch caller. Owns run-directory creation,
  one-time generation preflight and evidence persistence. Composition is
  adapter → New-BatchPlan → Invoke-BatchPlan.
#>
[CmdletBinding()]
param(
    [AllowEmptyCollection()] [string[]] $Path = @(),
    [string] $Selection = '',
    [string] $RunDirectory = '',
    [string] $PerlRoot = '',
    [string] $CdxsciRoot = '',
    [string] $PowerShellExecutable = '',
    [nullable[int]] $MaxWorkers = $null,
    [nullable[int]] $ReservedCores = $null,
    [nullable[int]] $ProcessTimeoutSeconds = $null,
    [nullable[int]] $WaitTimeoutSeconds = $null,
    [nullable[int]] $MinItemsPerWorker = $null,
    [switch] $SkipGenerate,
    [switch] $Preview,
    [switch] $AllowWriteCollisions
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)

. (Join-Path $PSScriptRoot 'latexai-common.ps1')
$runtime = Resolve-LaTeXAIRuntime -PerlRoot $PerlRoot -CdxsciRoot $CdxsciRoot `
    -PowerShellExecutable $PowerShellExecutable -RequirePerl -RequireCdxsci
Set-LaTeXAIRuntimeEnvironment -Runtime $runtime -IncludeCdxsci
$budgets = $runtime.Policy.Test.Budgets
if ($null -eq $ReservedCores) { $ReservedCores = [int]$budgets.ReservedCores }
if ($null -eq $ProcessTimeoutSeconds) { $ProcessTimeoutSeconds = [int]$budgets.ProcessTimeoutSeconds }
if ($null -eq $WaitTimeoutSeconds) { $WaitTimeoutSeconds = [int]$budgets.WaitTimeoutSeconds }
if ($null -eq $MinItemsPerWorker) { $MinItemsPerWorker = [int]$budgets.MinItemsPerWorker }

Import-Module -Name $runtime.ExecutorManifest -Force -ErrorAction Stop
. (Join-Path $PSScriptRoot 'test-jobs.ps1')

function Save-LaTeXAIJson {
    param([Parameter(Mandatory)] [string] $Path, [Parameter(Mandatory)] $Object)
    $dir = [System.IO.Path]::GetDirectoryName($Path)
    if ($dir) { [void][System.IO.Directory]::CreateDirectory($dir) }
    [System.IO.File]::WriteAllText($Path, (($Object | ConvertTo-Json -Depth 12) + "`n"), $utf8)
}

function Invoke-LaTeXAIGenerateOnce {
    $psi = [System.Diagnostics.ProcessStartInfo]::new($runtime.PerlPath)
    $psi.ArgumentList.Add($runtime.GenerateScript)
    $psi.WorkingDirectory = $runtime.CheckoutRoot
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $process = [System.Diagnostics.Process]::Start($psi)
    try {
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "lgen failed: $($stdout.GetAwaiter().GetResult())$($stderr.GetAwaiter().GetResult())"
        }
    }
    finally { $process.Dispose() }
}

if ([string]::IsNullOrWhiteSpace($Selection) -and @($Path).Count -eq 0) { $Selection = 'full' }

if ([string]::IsNullOrWhiteSpace($RunDirectory)) {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $leaf = '{0}_{1}' -f $stamp, [guid]::NewGuid().ToString('n').Substring(0, 8)
    $RunDirectory = Join-Path $runtime.CheckoutRoot (Join-Path 'temp\t\test-batches' $leaf)
}
else {
    if (-not [System.IO.Path]::IsPathRooted($RunDirectory)) {
        $RunDirectory = Join-Path $runtime.CheckoutRoot $RunDirectory
    }
    $RunDirectory = [System.IO.Path]::GetFullPath($RunDirectory)
}
[void][System.IO.Directory]::CreateDirectory($RunDirectory)

$jobs = @(Get-LaTeXAITestJob -RunDirectory $RunDirectory -Runtime $runtime `
    -Path $Path -Selection $Selection -TimeoutSeconds $ProcessTimeoutSeconds)

$jobViews = [System.Collections.Generic.List[object]]::new()
foreach ($job in $jobs) {
    $spec = $job.ProcessSpec
    $timeout = $null
    if ($spec -is [System.Collections.IDictionary] -and $spec.Contains('TimeoutSeconds')) {
        $timeout = $spec['TimeoutSeconds']
    }
    $jobViews.Add([ordered]@{
            id = $job.Id
            driver = $job.Metadata['RepositoryRelativePath']
            estimatedCost = $job.EstimatedCost
            resultPath = $job.Metadata['ResultPath']
            tapPath = $job.Metadata['TapPath']
            tempRoot = $job.Metadata['TempRoot']
            timeoutSeconds = $timeout
            writes = @($job.Writes)
        })
}
$previewObject = [ordered]@{
    operation = 'tap-batch'
    checkout = $runtime.CheckoutRoot
    cdxsci = $runtime.CdxsciRoot
    perl = $runtime.PerlPath
    powershell = $runtime.ChildPowerShell
    runDirectory = $RunDirectory
    budgets = [ordered]@{
        MaxWorkers = $MaxWorkers
        ReservedCores = $ReservedCores
        ProcessTimeoutSeconds = $ProcessTimeoutSeconds
        WaitTimeoutSeconds = $WaitTimeoutSeconds
        MinItemsPerWorker = $MinItemsPerWorker
    }
    generatedModules = $runtime.GeneratedModules
    trackedScripts = $runtime.TrackedScripts
    jobs = $jobViews.ToArray()
}
Save-LaTeXAIJson -Path (Join-Path $RunDirectory 'preview.json') -Object $previewObject
if ($Preview) {
    $previewObject | ConvertTo-Json -Depth 8
    return
}

if (-not $SkipGenerate) {
    Invoke-LaTeXAIGenerateOnce
}
else {
    foreach ($row in @($runtime.GeneratedModules)) {
        if (-not $row.present) { throw "generated module missing: $($row.path); run lgen or omit -SkipGenerate" }
    }
}

$compiled = batch-executor\New-BatchPlan -Job $jobs -BasePath $runtime.CheckoutRoot `
    -AllowWriteCollisions:$AllowWriteCollisions
Save-LaTeXAIJson -Path (Join-Path $RunDirectory 'plan.json') -Object ([ordered]@{
        errors = @($compiled.Errors)
        warnings = @($compiled.Warnings)
        plan = $compiled.Plan
    })
if ($compiled.Errors.Count -gt 0 -or $null -eq $compiled.Plan) {
    throw "test-run.ps1: plan validation failed: $(@($compiled.Errors) -join '; ')"
}

Write-Information -InformationAction Continue -MessageData (
    'TAP batch root: jobs={0}; run={1}' -f $jobs.Count, $RunDirectory)

$execution = $null
$invokeError = $null
try {
    $execution = batch-executor\Invoke-BatchPlan -Plan $compiled `
        -MaxWorkers $MaxWorkers -ReservedCores $ReservedCores `
        -MinItemsPerWorker $MinItemsPerWorker `
        -ProcessTimeoutSeconds $ProcessTimeoutSeconds -WaitTimeoutSeconds $WaitTimeoutSeconds `
        -PowerShellPath $runtime.ChildPowerShell.Executable -CreateNoWindow $true -WindowStyle Hidden
}
catch {
    $invokeError = $_
}

$results = @()
if ($execution -and $execution.PSObject.Properties['Results']) { $results = @($execution.Results) }
$observations = @(foreach ($item in $results) {
        if ($null -eq $item) { continue }
        $inputObject = $item.Input
        $meta = $null
        if ($inputObject -and $inputObject.PSObject.Properties['Metadata']) { $meta = $inputObject.Metadata }
        $resultFile = ''
        if ($meta -is [System.Collections.IDictionary] -and $meta.Contains('ResultPath')) {
            $resultFile = [string]$meta['ResultPath']
        }
        elseif ($meta) { $resultFile = [string]$meta.ResultPath }
        $tapEvidence = $null
        $missing = $true
        if ($resultFile -and (Test-Path -LiteralPath $resultFile -PathType Leaf)) {
            $tapEvidence = Get-Content -LiteralPath $resultFile -Raw | ConvertFrom-Json -DateKind String
            $missing = $false
        }
        $state = if ($item.PSObject.Properties['State']) { [string]$item.State }
            elseif ($item.PSObject.Properties['Status']) { [string]$item.Status }
            else { '' }
        $skipReasons = @()
        if ($tapEvidence -and $tapEvidence.tests) {
            foreach ($row in @($tapEvidence.tests)) {
                if ($row.PSObject.Properties['skip_all'] -and $row.skip_all) { $skipReasons += [string]$row.skip_all }
            }
        }
        [ordered]@{
            id = if ($inputObject) { [string]$inputObject.Id } else { $null }
            status = $state
            missingResult = $missing
            driver = if ($meta -is [System.Collections.IDictionary]) { [string]$meta['RepositoryRelativePath'] }
                elseif ($meta) { [string]$meta.RepositoryRelativePath } else { $null }
            aggregator = if ($tapEvidence) { $tapEvidence.aggregator } else { $null }
            skipAll = $skipReasons
        }
    })
$missingResults = @($observations | Where-Object missingResult).Count
$summary = if ($execution) { $execution.Summary } else { $null }
$report = [ordered]@{
    schema = 'latexai/tap-batch/0.1'
    runDirectory = $RunDirectory
    checkout = $runtime.CheckoutRoot
    trackedScripts = $runtime.TrackedScripts
    powershell = $runtime.ChildPowerShell
    perl = $runtime.PerlPath
    summary = $summary
    timing = if ($execution) { $execution.Timing } else { $null }
    errors = if ($execution) { @($execution.Errors) } else { @() }
    invokeError = if ($invokeError) { [string]$invokeError.Exception.Message } else { $null }
    observations = $observations
    missingResults = $missingResults
}
Save-LaTeXAIJson -Path (Join-Path $RunDirectory 'execution.json') -Object $report
if ($invokeError) { throw $invokeError }

$infrastructureErrors = @($report.errors).Count
Write-Information -InformationAction Continue -MessageData (
    'TAP batch: total={0}; succeeded={1}; failed={2}; timed-out={3}; cancelled={4}; missing-results={5}; infrastructure-errors={6}; duration-ms={7}' -f
    $summary.Total, $summary.Succeeded, $summary.Failed, $summary.TimedOut,
    $summary.Cancelled, $missingResults, $infrastructureErrors, $execution.Timing.TotalMs)

$execution
if ($null -eq $summary -or $summary.Succeeded -ne $summary.Total -or $infrastructureErrors -gt 0 -or $missingResults -gt 0) {
    throw ('test-run.ps1: batch did not succeed: failed={0}; timed-out={1}; cancelled={2}; missing-results={3}; infrastructure-errors={4}' -f
        $summary.Failed, $summary.TimedOut, $summary.Cancelled, $missingResults, $infrastructureErrors)
}
