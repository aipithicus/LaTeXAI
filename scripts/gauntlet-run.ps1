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
  Routine batches use ten workers and a 60-minute per-process timeout. Override
  -MaxWorkers for measured resource constraints or controlled profiling, and
  -ProcessTimeoutSeconds for a different job budget. -WaitTimeoutSeconds bounds
  the whole batch; its policy default is currently zero (unbounded wait) until
  I3 qualifies a finite batch budget.
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
    [switch] $Preview
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'latexai-common.ps1')
$runtime = Resolve-LaTeXAIRuntime -PerlRoot $PerlRoot -CdxsciRoot $CdxsciRoot `
    -PowerShellExecutable $PowerShellExecutable -RequirePerl -RequireCdxsci
Set-LaTeXAIRuntimeEnvironment -Runtime $runtime -IncludeCdxsci
$policy = $runtime.Policy.Gauntlet
if ($null -eq $MaxWorkers) { $MaxWorkers = [int]$policy.MaxWorkers }
if ($null -eq $ReservedCores) { $ReservedCores = [int]$policy.ReservedCores }
if ($null -eq $ProcessTimeoutSeconds) { $ProcessTimeoutSeconds = [int]$policy.ProcessTimeoutSeconds }
if ($null -eq $WaitTimeoutSeconds) { $WaitTimeoutSeconds = [int]$policy.WaitTimeoutSeconds }
if (-not $PSBoundParameters.ContainsKey('Preload')) { $Preload = @($policy.Preload) }

$engineRoot = $runtime.CheckoutRoot
$worker = Join-Path $PSScriptRoot 'gauntlet-worker.ps1'
if (-not (Test-Path -LiteralPath $worker -PathType Leaf)) { throw "worker not found: '$worker'" }
$perl = $runtime.PerlPath

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
        budgets = [ordered]@{
            MaxWorkers = $MaxWorkers
            ReservedCores = $ReservedCores
            ProcessTimeoutSeconds = $ProcessTimeoutSeconds
            WaitTimeoutSeconds = $WaitTimeoutSeconds
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
    $osName = & $perl -e 'print $^O' 2>$null
    if ($osName -ne 'MSWin32') { throw "perl at '$perl' is not the Windows build (`$^O=$osName)" }
    $loaded = & $perl -I lib -MLaTeXML -MXML::LibXML -e 'print $LaTeXML::VERSION' 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($loaded)) {
        throw "LaTeXML does not load under '$perl' with -I lib"
    }
    $engineVersion = [string]$loaded
    $engineCommit = (& git rev-parse --short HEAD 2>$null)
    if ($LASTEXITCODE -ne 0) { $engineCommit = 'unknown' }
    elseif (@(& git status --porcelain 2>$null).Count -gt 0) { $engineCommit = "$engineCommit+dirty" }
    if ($Kpsewhich) {
        $kpse = $runtime.Kpsewhich
        if (-not (Test-Path -LiteralPath $kpse -PathType Leaf)) {
            throw "kpsewhich shim missing: '$kpse'"
        }
        $env:LATEXML_KPSEWHICH = (Resolve-Path -LiteralPath $kpse).Path
        $env:LATEXML_KPSEWHICH_CACHE_ONLY = '1'
        $startup = & $kpse --expand-var
        $startupLines = @($startup -split "`r?`n" | Where-Object { $_ -ne '' })
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
