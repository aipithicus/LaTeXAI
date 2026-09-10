#requires -Version 7.5
# I3: a hung TAP job is terminated under its budget while a sibling completes.
[CmdletBinding()]
param(
    [string] $CdxsciRoot = '',
    [string] $PerlRoot = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'latexai-common.ps1')
$runtime = Resolve-LaTeXAIRuntime -PerlRoot $PerlRoot -CdxsciRoot $CdxsciRoot -RequirePerl -RequireCdxsci
$hang = Join-Path $PSScriptRoot 'tests\tap\hang.t'
$pass = Join-Path $PSScriptRoot 'tests\tap\pass.t'
$out = Join-Path $runtime.CheckoutRoot ('temp\t\test-batches\i3-timeout-' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
$failed = $false
try {
    & (Join-Path $PSScriptRoot 'test-run.ps1') -Path @($hang, $pass) -RunDirectory $out `
        -MaxWorkers 2 -SkipGenerate -ProcessTimeoutSeconds 8 -WaitTimeoutSeconds 40 `
        -PerlRoot $runtime.PerlRoot -CdxsciRoot $runtime.CdxsciRoot `
        -PowerShellExecutable $runtime.ChildPowerShell.Executable
}
catch { $failed = $true }
$execution = Get-Content -LiteralPath (Join-Path $out 'execution.json') -Raw | ConvertFrom-Json -DateKind String
$hangObs = @($execution.observations | Where-Object { $_.driver -like '*hang.t' })[0]
$passObs = @($execution.observations | Where-Object { $_.driver -like '*pass.t' })[0]
if (-not $failed) { throw 'timeout batch was reported successful' }
if ($passObs.status -ne 'Succeeded') { throw "sibling did not succeed: $($passObs.status)" }
if ($hangObs.status -notin @('TimedOut', 'Failed', 'Cancelled')) {
    throw "hung job status $($hangObs.status) was not a timeout/failure"
}
$tap = Join-Path $out 'tap-jobs'
$hangTap = Get-ChildItem -LiteralPath $tap -Recurse -Filter tap.txt | Where-Object { $_.DirectoryName -match 'hang' } | Select-Object -First 1
Write-Host "ok hung-job-timeout sibling=$($passObs.status) hung=$($hangObs.status) tap=$([bool]$hangTap)"
Write-Host "run $out"
