#requires -Version 7.5
<#
  scripts/gauntlet-run.ps1 — engine launcher for codex-scientiae inventory
  batches over the LaTeXAI engine.

  Preflights the engine runtime (Strawberry perl, LaTeXML loads, generated
  modules present), stamps engine version and commit once, then hands off to
  codex-scientiae's house caller src/batch-runner.ps1 with -Engine latexai
  -EngineRoot <this repo> -Worker gauntlet-worker.ps1.
  The runner mints artifacts/latexai/<stamp>/ under the codex root, plans
  one job per inventory row, runs them through the batch executor, and
  folds receipts into inventory-summary.jsonl and run.json.

  Examples (from the LaTeXAI root):
    scripts/gauntlet-run.ps1                       # whole gauntlet
    scripts/gauntlet-run.ps1 -Path supellex/gauntlet/interval-algebra
    scripts/gauntlet-run.ps1 -Path supellex/gauntlet/interval-algebra/1001.3251v2 -MaxWorkers 1
    scripts/gauntlet-run.ps1 -Profile               # per-macro profile in every receipt
    scripts/gauntlet-run.ps1 -Preview               # runtime/selection only; no conversion

  -Path entries are resolved by the runner against the codex root.
  -Profile adds the lxprofile.sty preload (LaTeXML's TRACE_PROFILE bit); the
  worker folds the log's "Profiling results" block into receipt details.profile.
  Routine batches use ten workers, a 60-minute per-process timeout and an
  8-hour batch wait. Pass -WaitTimeoutSeconds 0 only as an explicit unbounded
  diagnostic. -Package with -EvidenceDirectory is observed-route selection;
  -SelectOnly writes the frozen list without converting.
#>

[CmdletBinding()]
param(
    [string] $CdxsciRoot = '',
    [string] $PerlRoot = '',
    [string] $PowerShellExecutable = '',
    [string[]] $Path = @(),
    [nullable[int]] $MaxWorkers = $null,
    [nullable[int]] $ReservedCores = $null,
    [nullable[int]] $ProcessTimeoutSeconds = $null,
    [nullable[int]] $WaitTimeoutSeconds = $null,
    [string[]] $Preload,
    [bool] $IncludeStyles = $true,
    [string[]] $LatexmlArgument = @(),
    [bool] $Kpsewhich = $true,
    [switch] $Profile,
    [switch] $FailOnArticleFailure,
    [switch] $Preview,
    [string[]] $Package = @(),
    [ValidateSet('binding', 'raw', 'raw-local', 'missing', 'union')] [string] $PackageRoute = 'union',
    [string] $EvidenceDirectory = '',
    [switch] $SelectOnly,
    [ValidateSet('source', 'output')] [string] $ConversionWorkingDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'latexai-common.ps1')
. (Join-Path $PSScriptRoot 'gauntlet-select.ps1')
$runtime = Resolve-LaTeXAIRuntime -PerlRoot $PerlRoot -CdxsciRoot $CdxsciRoot `
    -PowerShellExecutable $PowerShellExecutable -RequirePerl -RequireCdxsci
Set-LaTeXAIRuntimeEnvironment -Runtime $runtime -IncludeCdxsci
$policy = $runtime.Policy.Gauntlet
if ($null -eq $MaxWorkers) { $MaxWorkers = [int]$policy.MaxWorkers }
if ($null -eq $ReservedCores) { $ReservedCores = [int]$policy.ReservedCores }
if ($null -eq $ProcessTimeoutSeconds) { $ProcessTimeoutSeconds = [int]$policy.ProcessTimeoutSeconds }
if ($null -eq $WaitTimeoutSeconds) { $WaitTimeoutSeconds = [int]$policy.WaitTimeoutSeconds }
if (-not $PSBoundParameters.ContainsKey('Preload')) { $Preload = @($policy.Preload) }
if (-not $PSBoundParameters.ContainsKey('ConversionWorkingDirectory')) {
    $ConversionWorkingDirectory = [string]$policy.ConversionWorkingDirectory
}
$nativeTimeout = [int]$policy.NativeTimeoutSeconds
if ($nativeTimeout -le 0) { $nativeTimeout = [int]$ProcessTimeoutSeconds }

$engineRoot = $runtime.CheckoutRoot
$worker = Join-Path $PSScriptRoot 'gauntlet-worker.ps1'
if (-not (Test-Path -LiteralPath $worker -PathType Leaf)) { throw "worker not found: '$worker'" }
$perl = $runtime.PerlPath

$packageSelection = $null
if (@($Package).Count -gt 0) {
    if ([string]::IsNullOrWhiteSpace($EvidenceDirectory)) {
        throw 'LaTeXAI: -Package requires -EvidenceDirectory naming a retained gauntlet run with receipt.json files.'
    }
    $packageSelection = Select-LaTeXAIGauntletPackage -CdxsciRoot $runtime.CdxsciRoot `
        -EvidenceDirectory $EvidenceDirectory -Package $Package -Route $PackageRoute
    $Path = @($packageSelection.selected | ForEach-Object { $_.path })
    if ($SelectOnly) {
        $packageSelection | ConvertTo-Json -Depth 8
        return
    }
    if ($Path.Count -eq 0 -and -not $Preview) {
        throw 'LaTeXAI: package selection produced no inventory articles. See incompleteness in the selection object.'
    }
}

if ($Preview) {
    [ordered]@{
        operation = 'gauntlet'
        checkout = $engineRoot
        cdxsci = $runtime.CdxsciRoot
        perl = $perl
        powershell = $runtime.ChildPowerShell
        kpsewhich = $runtime.Kpsewhich
        worker = $worker
        path = @($Path)
        conversionWorkingDirectory = $ConversionWorkingDirectory
        packageSelection = $packageSelection
        budgets = [ordered]@{
            requested = [ordered]@{
                MaxWorkers = $MaxWorkers
                ReservedCores = $ReservedCores
                ProcessTimeoutSeconds = $ProcessTimeoutSeconds
                WaitTimeoutSeconds = $WaitTimeoutSeconds
                NativeTimeoutSeconds = $nativeTimeout
            }
            policy = $policy
            unboundedWait = [bool]($WaitTimeoutSeconds -eq 0)
        }
        trackedScripts = $runtime.TrackedScripts
        generatedModules = $runtime.GeneratedModules
    } | ConvertTo-Json -Depth 8
    return
}

foreach ($generated in @('lib/LaTeXML/Version.pm', 'lib/LaTeXML/MathGrammar.pm')) {
    if (-not (Test-Path -LiteralPath (Join-Path $engineRoot $generated) -PathType Leaf)) {
        throw "'$generated' is missing: run lgen (perl tools/dev/generate.pl) first"
    }
}

Push-Location $engineRoot
try {
    $osProbe = Invoke-LaTeXAINative -FilePath $perl -Arguments @('-e', 'print $^O') -WorkingDirectory $engineRoot -TimeoutSeconds 30
    if ($osProbe.TimedOut -or $osProbe.StdOut.Trim() -ne 'MSWin32') {
        throw "perl at '$perl' is not the Windows build (outcome=$($osProbe.Outcome) `$^O=$($osProbe.StdOut))"
    }
    $loadProbe = Invoke-LaTeXAINative -FilePath $perl -Arguments @('-I', 'lib', '-MLaTeXML', '-MXML::LibXML', '-e', 'print $LaTeXML::VERSION') `
        -WorkingDirectory $engineRoot -TimeoutSeconds 60
    if ($loadProbe.TimedOut -or $loadProbe.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($loadProbe.StdOut)) {
        throw "LaTeXML does not load under '$perl' with -I lib ($($loadProbe.Outcome))"
    }
    $engineVersion = [string]$loadProbe.StdOut
    $gitProbe = Invoke-LaTeXAINative -FilePath 'git' -Arguments @('rev-parse', '--short', 'HEAD') -WorkingDirectory $engineRoot -TimeoutSeconds 30
    $engineCommit = if ($gitProbe.ExitCode -eq 0) { $gitProbe.StdOut.Trim() } else { 'unknown' }
    $dirtyProbe = Invoke-LaTeXAINative -FilePath 'git' -Arguments @('status', '--porcelain') -WorkingDirectory $engineRoot -TimeoutSeconds 30
    if ($engineCommit -ne 'unknown' -and @($dirtyProbe.StdOut -split "`r?`n" | Where-Object { $_ -ne '' }).Count -gt 0) {
        $engineCommit = "$engineCommit+dirty"
    }
    if ($Kpsewhich) {
        $kpse = $runtime.Kpsewhich
        if (-not (Test-Path -LiteralPath $kpse -PathType Leaf)) {
            throw "kpsewhich shim missing: '$kpse'"
        }
        $env:LATEXML_KPSEWHICH = (Resolve-Path -LiteralPath $kpse).Path
        $env:LATEXML_KPSEWHICH_CACHE_ONLY = '1'
        $kpsePl = Join-Path $engineRoot 'tools\dev\kpsewhich.pl'
        $startup = Invoke-LaTeXAINative -FilePath $perl -Arguments @($kpsePl, '--expand-var') `
            -WorkingDirectory $engineRoot -TimeoutSeconds 30
        if ($startup.TimedOut -or $startup.ExitCode -ne 0) {
            throw "kpsewhich shim startup failed ($($startup.Outcome)): $($startup.StdErr)"
        }
        $startupLines = @($startup.StdOut -split "`r?`n" | Where-Object { $_ -ne '' })
        if ($startupLines.Count -lt 2) {
            throw "kpsewhich shim startup call returned $($startupLines.Count) line(s), expected the lib-ctan root and the same path with a trailing slash"
        }
    }
    else {
        Remove-Item -LiteralPath Env:LATEXML_KPSEWHICH -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath Env:LATEXML_KPSEWHICH_CACHE_ONLY -ErrorAction SilentlyContinue
    }
}
finally { Pop-Location }

Write-Information -InformationAction Continue -MessageData (
    'LaTeXAI gauntlet: engine={0} commit={1} perl={2} cdxsci={3}' -f $engineVersion, $engineCommit, $perl, $runtime.CdxsciRoot)

$workerParameter = @{
    PerlPath = $perl
    EngineVersion = $engineVersion
    EngineCommit = $engineCommit
    IncludeStyles = $IncludeStyles
    SearchPath = @($policy.SearchPath)
    Kpsewhich = $Kpsewhich
    TimeoutSeconds = $nativeTimeout
    ConversionWorkingDirectory = $ConversionWorkingDirectory
}
$preloads = @($Preload | Where-Object { $_ })
if ($Profile -and ($preloads -notcontains 'lxprofile.sty')) { $preloads += 'lxprofile.sty' }
if ($preloads.Count -gt 0) { $workerParameter.Preload = $preloads }
if (@($LatexmlArgument | Where-Object { $_ }).Count -gt 0) {
    $workerParameter.LatexmlArgument = @($LatexmlArgument | Where-Object { $_ })
}

$invoke = @{
    RepositoryRoot = $runtime.CdxsciRoot
    Engine = 'latexai'
    EngineRoot = $engineRoot
    Worker = $worker
    WorkerParameter = $workerParameter
    PowerShellPath = $runtime.ChildPowerShell.Executable
    MaxWorkers = $MaxWorkers
    ReservedCores = $ReservedCores
    ProcessTimeoutSeconds = $ProcessTimeoutSeconds
    WaitTimeoutSeconds = $WaitTimeoutSeconds
    FailOnArticleFailure = $FailOnArticleFailure
}
if (@($Path).Count -gt 0) { $invoke.Path = $Path }

& $runtime.BatchRunner @invoke
exit $LASTEXITCODE
