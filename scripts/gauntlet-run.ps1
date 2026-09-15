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
  freezes experiment.json and aggregates worker run.json records into batch.json.

  Examples (from the LaTeXAI root):
    scripts/gauntlet-run.ps1                       # whole gauntlet
    scripts/gauntlet-run.ps1 -Path supellex/gauntlet/interval-algebra
    scripts/gauntlet-run.ps1 -Path supellex/gauntlet/interval-algebra/1001.3251v2 -MaxWorkers 1
    scripts/gauntlet-run.ps1 -Profile               # per-macro profile in every condition
    scripts/gauntlet-run.ps1 -Preview               # runtime/selection only; no conversion

  -Path entries are resolved by the runner against the codex root.
  -Profile adds the lxprofile.sty preload (LaTeXML's TRACE_PROFILE bit); the
  worker folds the log's "Profiling results" block into condition details.profile.
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
    [nullable[int]] $NativeTimeoutSeconds = $null,
    [nullable[int]] $WaitTimeoutSeconds = $null,
    [nullable[int]] $ExecutionTimeoutSeconds = $null,
    [nullable[int]] $CleanupTimeoutSeconds = $null,
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
    [switch] $LegacyInventory,
    [switch] $SelectOnly,
    [switch] $CaptureParity,
    [string] $ReuseBatch = '',
    [switch] $AnalysisOnly,
    [string[]] $OffArgument = @(),
    [string[]] $OnArgument = @(),
    [switch] $OnFirst,
    [ValidateRange(1, 86400)] [int] $ComparisonTimeoutSeconds = 900,
    [string] $RunDirectory = '',
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
$reuse=$null
if($AnalysisOnly -and -not $ReuseBatch){throw '-AnalysisOnly requires -ReuseBatch with frozen paper records'}
if($ReuseBatch){
    Import-Module (Join-Path $runtime.CdxsciRoot 'src/inventory-records/inventory-records.psm1') -Force
    . (Join-Path $PSScriptRoot 'gauntlet-reuse.ps1')
    $reuse=New-LaTeXAIReusePlan -Directory $ReuseBatch -AnalysisOnly:$AnalysisOnly
    $CaptureParity=$true
    if(-not $Path.Count){$Path=@($reuse.Plan.assignments.article.directory)}
    foreach($name in @('IncludeStyles','Kpsewhich','Preload','ConversionWorkingDirectory')){
        if(-not $PSBoundParameters.ContainsKey($name)){
            $value=if($reuse.Plan.workerParameters.Contains($name)){$reuse.Plan.workerParameters[$name]}else{@()}
            Set-Variable -Name $name -Value $value
            $PSBoundParameters[$name]=$value
        }
    }
    if($null -eq $NativeTimeoutSeconds){$NativeTimeoutSeconds=[int]$reuse.Plan.workerParameters.TimeoutSeconds}
    if(-not $PSBoundParameters.ContainsKey('OffArgument')){$OffArgument=@(($reuse.Plan.specification.conditions|Where-Object {$_.id -ceq 'off'}).arguments)}
    if(-not $PSBoundParameters.ContainsKey('OnArgument')){$OnArgument=@(($reuse.Plan.specification.conditions|Where-Object {$_.id -ceq 'on'}).arguments|Where-Object {$_ -cne '--capture'})}
}
if ($null -eq $MaxWorkers) { $MaxWorkers = [int]$policy.MaxWorkers }
if ($null -eq $ReservedCores) { $ReservedCores = [int]$policy.ReservedCores }
if ($null -eq $NativeTimeoutSeconds) { $NativeTimeoutSeconds = [int]$policy.NativeTimeoutSeconds }
if ($null -eq $ProcessTimeoutSeconds) {
    $ProcessTimeoutSeconds = if($AnalysisOnly){$ComparisonTimeoutSeconds+600} elseif ($CaptureParity) { 2 * ($NativeTimeoutSeconds + 60) + $ComparisonTimeoutSeconds + 300 }
        elseif ($NativeTimeoutSeconds -eq 0) { 0 }
        else { $NativeTimeoutSeconds + [int]$policy.WorkerGraceSeconds }
}
if ($null -eq $WaitTimeoutSeconds) { $WaitTimeoutSeconds = [int]$policy.WaitTimeoutSeconds }
if ($null -eq $ExecutionTimeoutSeconds) { $ExecutionTimeoutSeconds = [int]$policy.ExecutionTimeoutSeconds }
if ($null -eq $CleanupTimeoutSeconds) { $CleanupTimeoutSeconds = [int]$policy.CleanupTimeoutSeconds }
if (-not $PSBoundParameters.ContainsKey('Preload')) { $Preload = @($policy.Preload) }
if (-not $PSBoundParameters.ContainsKey('ConversionWorkingDirectory')) {
    $ConversionWorkingDirectory = [string]$policy.ConversionWorkingDirectory
}
$nativeTimeout = [int]$NativeTimeoutSeconds
if ($CaptureParity) {
    $minimum=($AnalysisOnly ? ($ComparisonTimeoutSeconds+60) : (2*$nativeTimeout+$ComparisonTimeoutSeconds+60))
    if ($nativeTimeout -le 0 -or $ProcessTimeoutSeconds -lt $minimum) { throw 'Paired workers require finite budgets covering requested stages and cleanup' }
    if ($PSBoundParameters.ContainsKey('ConversionWorkingDirectory') -and $ConversionWorkingDirectory -ne 'output') { throw 'Paired conditions require isolated output working directories' }
    $ConversionWorkingDirectory='output'
    foreach($argument in @($LatexmlArgument)+@($OffArgument)+@($OnArgument)){
        # No positional values or file-taking options: these could read outside
        # the frozen trees. Getopt::Long accepts abbreviated option names.
        if($argument -notmatch '^--([a-z][a-z0-9-]*)$'){throw 'Paired extra arguments must be standalone flags'}
        $option=$Matches[1]
        if(@('capture','nocapture','no-capture','path','log','destination','output','preload','preamble','postamble','init','inputencoding','debug','documentid') |
                Where-Object {$_.StartsWith($option,[StringComparison]::OrdinalIgnoreCase)}){throw 'Paired capture and file-taking arguments are owned by the experiment'}
    }
    if(@($Preload|Where-Object {$_ -match '[\\/:]' -or $_ -match '\.\.'}).Count){throw 'Paired preloads must be module names resolved within frozen trees'}
    foreach($search in $policy.SearchPath){
        if([IO.Path]::IsPathRooted($search) -or $search -match '(^|[\\/])\.\.([\\/]|$)' -or $search -notmatch '^(lib|lib-ctan|scripts|tools/dev)([\\/]|$)'){
            throw 'Paired search paths must be inside copied engine input trees'
        }
    }
} elseif ($OffArgument.Count -or $OnArgument.Count -or $OnFirst) { throw 'Condition arguments/order require -CaptureParity' }

$engineRoot = $runtime.CheckoutRoot
$worker = Join-Path $PSScriptRoot 'gauntlet-worker.ps1'
if (-not (Test-Path -LiteralPath $worker -PathType Leaf)) { throw "worker not found: '$worker'" }
$perl = $runtime.PerlPath

$packageSelection = $null
if (@($Package).Count -gt 0) {
    if ([string]::IsNullOrWhiteSpace($EvidenceDirectory)) {
        throw 'LaTeXAI: -Package requires -EvidenceDirectory naming a retained inventory batch; old receipts require -LegacyInventory.'
    }
    $packageSelection = Select-LaTeXAIGauntletPackage -CdxsciRoot $runtime.CdxsciRoot `
        -EvidenceDirectory $EvidenceDirectory -Package $Package -Route $PackageRoute -LegacyInventory:$LegacyInventory
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
        conditions = ($CaptureParity ? @('off','on') : @('conversion'))
        order = ($CaptureParity ? ($OnFirst ? @('on','off') : @('off','on')) : @('conversion'))
        comparisonTimeoutSeconds = ($CaptureParity ? $ComparisonTimeoutSeconds : $null)
        frozenInputCopies = [bool]$CaptureParity
        reuse = ($reuse ? $reuse.Specification : $null)
        packageSelection = $packageSelection
        budgets = [ordered]@{
            requested = [ordered]@{
                MaxWorkers = $MaxWorkers
                ReservedCores = $ReservedCores
                ProcessTimeoutSeconds = $ProcessTimeoutSeconds
                WaitTimeoutSeconds = $WaitTimeoutSeconds
                ExecutionTimeoutSeconds = $ExecutionTimeoutSeconds
                CleanupTimeoutSeconds = $CleanupTimeoutSeconds
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
    $git = (Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $gitProbe = Invoke-LaTeXAINative -FilePath $git -Arguments @('rev-parse', '--short', 'HEAD') -WorkingDirectory $engineRoot -TimeoutSeconds 30
    if ($gitProbe.ExitCode -ne 0 -or -not $gitProbe.CleanupComplete) { throw "git identity probe failed: $($gitProbe.StdErr)" }
    $engineCommit = $gitProbe.StdOut.Trim()
    $dirtyProbe = Invoke-LaTeXAINative -FilePath $git -Arguments @('status', '--porcelain') -WorkingDirectory $engineRoot -TimeoutSeconds 30
    if ($dirtyProbe.ExitCode -ne 0 -or -not $dirtyProbe.CleanupComplete) { throw "git status probe failed: $($dirtyProbe.StdErr)" }
    if (@($dirtyProbe.StdOut -split "`r?`n" | Where-Object { $_ -ne '' }).Count -gt 0) {
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
    ExperimentSpecification = @{
        schema='latexai/acquisition-plan/1'
        conditions=@(@{id='conversion';capture=('--capture' -in $LatexmlArgument)})
        comparisons=@()
        payloadSchema=@{path=(Join-Path $PSScriptRoot 'schemas/paper-experiment.schema.json');sha256=(Get-LaTeXAIFileSha256 (Join-Path $PSScriptRoot 'schemas/paper-experiment.schema.json'))}
    }
    PowerShellPath = $runtime.ChildPowerShell.Executable
    MaxWorkers = $MaxWorkers
    ReservedCores = $ReservedCores
    ProcessTimeoutSeconds = $ProcessTimeoutSeconds
    WaitTimeoutSeconds = $WaitTimeoutSeconds
    ExecutionTimeoutSeconds = $ExecutionTimeoutSeconds
    CleanupTimeoutSeconds = $CleanupTimeoutSeconds
    FailOnArticleFailure = $FailOnArticleFailure
}
if (@($Path).Count -gt 0) { $invoke.Path = $Path }
if ($RunDirectory) { $invoke.RunDirectory=$RunDirectory }
Import-Module (Join-Path $runtime.CdxsciRoot 'src/inventory-records/inventory-records.psm1') -Force
$invoke.ExperimentSpecification.measurement=Get-InventoryFileReference (Join-Path $PSScriptRoot 'gauntlet-measure.ps1')
if($CaptureParity){
    . (Join-Path $runtime.CdxsciRoot 'src/infrastructure/containment.ps1')
    . (Join-Path $PSScriptRoot 'gauntlet-freeze.ps1')
    Import-Module (Join-Path $runtime.CdxsciRoot 'src/batch-adapters/adapters.psd1') -Force
    $runRoot=if($RunDirectory){Resolve-ArtifactRunDirectory -RunDirectory $RunDirectory -RepositoryRoot $runtime.CdxsciRoot}else{New-ModuleRunDir -Module latexai -RepositoryRoot $runtime.CdxsciRoot}
    $selection=if($Path.Count){$Path}else{@('supellex/gauntlet')}
    $jobs=@(Get-InventoryBatchJob -Path $selection -RunDirectory $runRoot -RepositoryRoot $runtime.CdxsciRoot `
        -Engine latexai -EngineRoot $engineRoot -Worker $worker -WorkerParameter $workerParameter)
    if($jobs.Count -eq 0){throw 'Paired experiment selected no papers'}
    $freeze=New-LaTeXAIExperimentFreeze -Directory (Join-Path $runRoot 'inputs') -EngineRoot $engineRoot -PerlRoot $runtime.PerlRoot `
        -CdxsciRoot $runtime.CdxsciRoot -Jobs $jobs -PowerShellExecutable $runtime.ChildPowerShell.Executable
    $invoke.RunDirectory=$runRoot
    $invoke.EngineRoot=$freeze.Record.engine
    $invoke.Worker=Join-Path $freeze.Record.engine 'scripts/gauntlet-worker.ps1'
    $invoke.WorkerParameter.PerlPath=$freeze.Record.perl
    $invoke.WorkerParameter.EngineCommit=$freeze.Record.engineCommit+($freeze.Record.engineDirty.Count ? '+dirty' : '')
    $invoke.RequireQualification=$true
    $declared=@{
        off=@{id='off';capture=$false;arguments=@($LatexmlArgument)+@($OffArgument)}
        on=@{id='on';capture=$true;arguments=@($LatexmlArgument)+@($OnArgument)+@('--capture')}
    }
    $order=($OnFirst ? @('on','off') : @('off','on'))
    $invoke.ExperimentSpecification=@{
        schema='latexai/paired-plan/1';freeze=$freeze.Reference
        conditions=@($order|ForEach-Object {$declared[$_]})
        comparisons=@(@{id='parity';left='off';right='on';mode='parity';required=$true})
        payloadSchema=(Get-InventoryFileReference (Join-Path $freeze.Record.engine 'scripts/schemas/paper-experiment.schema.json'))
        measurement=(Get-InventoryFileReference (Join-Path $freeze.Record.engine 'scripts/gauntlet-measure.ps1'))
        model=(Get-InventoryFileReference (Join-Path $freeze.Record.engine 'lib/LaTeXML/resources/RelaxNG/LaTeXML.model'))
        comparisonTimeoutSeconds=$ComparisonTimeoutSeconds
        stages=@{nativeTimeoutSeconds=$nativeTimeout;comparisonTimeoutSeconds=$ComparisonTimeoutSeconds;validationAllowanceSeconds=300;paperTimeoutSeconds=$ProcessTimeoutSeconds}
        orderPolicy=($OnFirst ? 'on-then-off' : 'off-then-on');maxPaperWorkers=$MaxWorkers
    }
    if($reuse){$invoke.ExperimentSpecification.reuse=$reuse.Specification}
    Write-Information -InformationAction Continue "Frozen paired experiment: $runRoot; papers=$($jobs.Count)"
}

& $runtime.BatchRunner @invoke
$runnerExit = if (Get-Variable -Name LASTEXITCODE -ErrorAction SilentlyContinue) { [int]$LASTEXITCODE } else { 0 }
exit $runnerExit
