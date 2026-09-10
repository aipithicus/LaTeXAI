#requires -Version 7.5
<#
  scripts/test-worker.ps1 — one TAP job. The executor owns the process deadline.
  This entrypoint runs tools/dev/tap-run.pl serially over the declared driver
  and leaves TAP plus JSON on disk before signalling failure.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Driver,
    [Parameter(Mandatory)] [string] $ResultPath,
    [Parameter(Mandatory)] [string] $TapPath,
    [Parameter(Mandatory)] [string] $StdOutPath,
    [Parameter(Mandatory)] [string] $StdErrPath,
    [Parameter(Mandatory)] [string] $CheckoutRoot,
    [Parameter(Mandatory)] [string] $PerlPath,
    [Parameter(Mandatory)] [string] $TapRunScript,
    [Parameter(Mandatory)] [string] $LibDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)

function Invoke-Native {
    param(
        [Parameter(Mandatory)] [string] $FilePath,
        [string[]] $Arguments = @(),
        [string] $WorkingDirectory = ''
    )
    $psi = [System.Diagnostics.ProcessStartInfo]::new($FilePath)
    foreach ($argument in $Arguments) { $psi.ArgumentList.Add($argument) }
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }
    $process = [System.Diagnostics.Process]::Start($psi)
    try {
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            StdOut = $stdoutTask.GetAwaiter().GetResult()
            StdErr = $stderrTask.GetAwaiter().GetResult()
        }
    }
    finally { $process.Dispose() }
}

foreach ($path in @($ResultPath, $TapPath, $StdOutPath, $StdErrPath)) {
    $dir = [System.IO.Path]::GetDirectoryName($path)
    if ($dir) { [void][System.IO.Directory]::CreateDirectory($dir) }
}

if (-not (Test-Path -LiteralPath $PerlPath -PathType Leaf)) { throw "PerlPath not found: '$PerlPath'" }
if (-not (Test-Path -LiteralPath $TapRunScript -PathType Leaf)) { throw "tap-run.pl not found: '$TapRunScript'" }
if (-not (Test-Path -LiteralPath $Driver -PathType Leaf)) { throw "driver not found: '$Driver'" }

$arguments = @(
    $TapRunScript
    '--lib', $LibDirectory
    '--tap', $TapPath
    '--result', $ResultPath
    '--cwd', $CheckoutRoot
    $Driver
)
$run = Invoke-Native -FilePath $PerlPath -Arguments $arguments -WorkingDirectory $CheckoutRoot
[System.IO.File]::WriteAllText($StdOutPath, [string]$run.StdOut, $utf8)
[System.IO.File]::WriteAllText($StdErrPath, [string]$run.StdErr, $utf8)

if (-not (Test-Path -LiteralPath $ResultPath -PathType Leaf)) {
    throw "TAP worker produced no result.json for '$Driver' (exit $($run.ExitCode))"
}
$result = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json -DateKind String
if ($null -eq $result -or $result.schema -ne 'latexai/tap-job/0.1' -or -not $result.complete) {
    throw "TAP worker result is incomplete for '$Driver'"
}
$problems = [bool]$result.aggregator.has_problems
$incomplete = [bool]$result.incomplete
if ($run.ExitCode -ne 0 -or $problems -or $incomplete) {
    $status = [string]$result.aggregator.status
    throw ("TAP failed for {0}: exit={1} status={2} failed={3} parse_errors={4}" -f
        $Driver, $run.ExitCode, $status, $result.aggregator.failed, $result.aggregator.parse_errors)
}
