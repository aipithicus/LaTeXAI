#requires -Version 7.5
# One assigned paper owns all its condition execution, comparison and publication.
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Article,
    [Parameter(Mandatory)] [string] $OutDirectory,
    [Parameter(Mandatory)] [string] $EngineRoot,
    [Parameter(Mandatory)] [string] $SourceTree,
    [Parameter(Mandatory)] [string] $Entrypoint,
    [Parameter(Mandatory)] [string] $TreeSha256,
    [Parameter(Mandatory)] [System.Collections.IDictionary] $RunContext,
    [string] $PerlPath = '',
    [string] $EngineVersion = '',
    [string] $EngineCommit = '',
    [string[]] $Preload = @(),
    [string[]] $SearchPath = @(),
    [bool] $IncludeStyles = $true,
    [string[]] $LatexmlArgument = @(),
    [bool] $Kpsewhich = $true,
    [int] $TimeoutSeconds = -1,
    [ValidateSet('source', 'output')] [string] $ConversionWorkingDirectory = 'source'
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'latexai-common.ps1')
. (Join-Path $PSScriptRoot 'gauntlet-convert.ps1')
. (Join-Path $PSScriptRoot 'gauntlet-freeze.ps1')
. (Join-Path $PSScriptRoot 'gauntlet-reuse.ps1')
. (Join-Path $PSScriptRoot 'gauntlet-legacy.ps1')
Import-Module $RunContext.recordsModule -Force
$assignment=Get-PaperRunAssignment -Context $RunContext
foreach($entry in @{directory=$Article;sourceTree=$SourceTree;entrypoint=$Entrypoint;treeSha256=$TreeSha256}.GetEnumerator()){
    if($assignment.Assignment.article[$entry.Key] -cne $entry.Value){throw "Worker arguments disagree with assignment: $($entry.Key)"}
}
foreach($key in $assignment.Plan.workerParameters.Keys){
    if(-not $PSBoundParameters.ContainsKey($key) -or
        (ConvertTo-Json -InputObject $PSBoundParameters[$key] -Depth 30 -Compress) -cne
        (ConvertTo-Json -InputObject $assignment.Plan.workerParameters[$key] -Depth 30 -Compress)){throw "Worker parameter differs from frozen experiment: $key"}
}
$spec=$assignment.Plan.specification
$contrast=$spec.schema -ceq 'latexai/contrast-plan/1'
$paired=$contrast -or $spec.schema -ceq 'latexai/paired-plan/1'
if(-not $paired -and $spec.schema -cne 'latexai/acquisition-plan/1'){throw 'Unsupported LaTeXAI experiment plan'}
$payloadSchema=Join-Path $PSScriptRoot 'schemas/paper-experiment.schema.json'
if((Get-InventoryFileReference $payloadSchema).sha256 -cne $spec.payloadSchema.sha256){throw 'Payload schema differs from frozen experiment'}
$measurement=if($spec.Contains('measurement')){$spec.measurement}else{$assignment.Plan.worker}
if($spec.Contains('measurement') -and (Get-InventoryFileReference (Join-Path $PSScriptRoot 'gauntlet-measure.ps1')).sha256 -cne $measurement.sha256){throw 'Changed measurement implementation'}
if($contrast){
    $null=Read-LaTeXAIPinnedJson $spec.declaration
    $ids=@($spec.conditions.id)
    if(-not $ids.Count -or @($ids|Sort-Object -Unique).Count -ne $ids.Count -or $ConversionWorkingDirectory -cne 'output'){throw 'Invalid contrast conditions'}
    foreach($condition in $spec.conditions){
        if(@($condition.arguments|Where-Object {$_ -ceq '--capture'}).Count -ne [int]$condition.capture){throw 'Contrast capture arguments disagree'}
    }
    foreach($edge in $spec.comparisons){if($edge.left -cnotin $ids -or $edge.right -cnotin $ids -or $edge.mode -cnotin @('parity','regression','styles')){throw 'Invalid contrast edge'}}
}elseif($paired){
    if(@($spec.conditions).Count -ne 2 -or @($spec.comparisons).Count -ne 1 -or
        ($spec.conditions.id -join ',') -notin @('off,on','on,off') -or $spec.comparisons[0].left -cne 'off' -or
        $spec.comparisons[0].right -cne 'on' -or $spec.comparisons[0].mode -cne 'parity' -or
        -not $spec.comparisons[0].required -or $ConversionWorkingDirectory -cne 'output'){throw 'Invalid paired experiment specification'}
    foreach($condition in $spec.conditions){
        if($condition.capture -ne ($condition.id -ceq 'on') -or
            @($condition.arguments|Where-Object {$_ -ceq '--capture'}).Count -ne [int]$condition.capture){throw 'Paired capture arguments disagree with condition roles'}
    }
}else{
    if($spec.conditions.Count -ne 1 -or $spec.conditions[0].id -cne 'conversion' -or $spec.comparisons.Count -ne 0 -or
        $spec.conditions[0].capture -ne ('--capture' -cin $LatexmlArgument)){throw 'Unsupported or inconsistent acquisition conditions'}
}
$paperDirectory=[IO.Path]::GetFullPath($OutDirectory)
$startedUtc=[datetime]::UtcNow
$conditions=[Collections.Generic.List[object]]::new()
$comparisons=[Collections.Generic.List[object]]::new()
$artifacts=[Collections.Generic.List[object]]::new()
$problems=[Collections.Generic.List[string]]::new()
$validationMs=0.0
$terminalWritten=$false
$frozen=$null
$retained=[Collections.Generic.List[object]]::new()
$imports=[Collections.Generic.List[object]]::new()
$conditionFreezes=@{}
foreach($requested in $spec.conditions){
    $conditions.Add(@{id=$requested.id;status='pending';engine=@{root=$EngineRoot;version=$EngineVersion;commit=$EngineCommit}
        execution=@{outcome='not-started';exitCode=$null;timedOut=$null;cleanupComplete=$null};outputs=@{};counts=@{};details=@{}})
}
function Add-PaperArtifact {
    param([string]$Path)
    if(Test-Path -LiteralPath $Path -PathType Leaf){
        $relative=[IO.Path]::GetRelativePath($paperDirectory,$Path).Replace('\','/')
        if(@($artifacts|Where-Object {$_.path -ceq $relative}).Count){return}
        $artifacts.Add(@{path=$relative;sha256=(Get-InventoryFileReference $Path).sha256;bytes=(Get-Item -LiteralPath $Path).Length})
    }
}
function Publish-Paper {
    param([switch]$Terminal)
    $conditionComplete=@($conditions|Where-Object {$_.status -ne 'ok'}).Count -eq 0
    $comparisonComplete=$comparisons.Count -eq $spec.comparisons.Count -and @($comparisons|Where-Object {$_.status -eq 'incomplete'}).Count -eq 0
    $complete=$conditionComplete -and $comparisonComplete -and $problems.Count -eq 0
    $qualification=if(-not $Terminal -or -not $complete){'incomplete'}elseif(-not $paired -or $spec.comparisons.Count -eq 0){'not-requested'}elseif(@($comparisons|Where-Object {$_.required -and $_.status -ne 'pass'}).Count){'fail'}else{'pass'}
    $summary=@{}
    foreach($condition in $conditions){foreach($key in $condition.counts.Keys){if(-not $summary.ContainsKey($key)){$summary[$key]=0.0};$summary[$key]+=$condition.counts[$key]}}
    if($paired){$summary.inputValidationMs=$validationMs;$summary.comparisonMs=0.0;foreach($comparison in $comparisons){$summary.comparisonMs+=$comparison.durationMs}}
    if($paired){
        $summary.conversionsExecuted=@($conditions|Where-Object {$_.Contains('conversion') -and $_.conversion.action -ceq 'executed'}).Count
        $summary.conversionsReused=@($conditions|Where-Object {$_.Contains('conversion') -and $_.conversion.action -ceq 'reused'}).Count
        $summary.conversionsRejected=@($conditions|Where-Object {$_.Contains('conversion') -and $_.conversion.action -ceq 'rejected'}).Count
        $summary.conversionsImported=@($conditions|Where-Object {$_.Contains('legacy')}).Count
    }
    $payload=@{schema='latexai/paper-experiment/1';measurement=$measurement;conditions=$conditions.ToArray();comparisons=$comparisons.ToArray()}
    if($paired){$payload.freeze=$spec.freeze;$payload.order=@($spec.conditions.id);$payload.integrityIssues=$problems.ToArray()}
    if($spec.Contains('reuse')){$payload.reuse=$spec.reuse}
    if(-not (Test-Json -Json ($payload|ConvertTo-Json -Depth 100) -SchemaFile $payloadSchema -ErrorAction Stop)){throw 'Invalid LaTeXAI paper payload'}
    $qualificationIssues=@($problems.ToArray())+@($comparisons|Where-Object {$_.status -eq 'incomplete' -or ($_.required -and $_.status -ne 'pass')}|ForEach-Object {$_.issues})
    $record=@{schema='codex-scientiae/paper-run/1';jobId=$assignment.Assignment.jobId;attemptId=$assignment.Assignment.attemptId
        experiment=$assignment.Experiment;article=$assignment.Assignment.article
        producer=@{engine='latexai';version=$EngineVersion;commit=$EngineCommit;worker=$assignment.Plan.worker}
        status=($Terminal ? ($complete ? 'complete' : 'failed') : 'running')
        startedUtc=$startedUtc.ToString('o');endedUtc=($Terminal ? [datetime]::UtcNow.ToString('o') : $null)
        durationMs=([datetime]::UtcNow-$startedUtc).TotalMilliseconds;summary=$summary;artifacts=$artifacts.ToArray();payload=$payload
        qualification=@{status=$qualification;issues=@($qualificationIssues)}
    }
    Write-PaperRun -OutDirectory $paperDirectory -Record $record
    if($Terminal){$script:terminalWritten=$true}
}
function Test-FrozenInputs {
    $watch=[Diagnostics.Stopwatch]::StartNew()
    try{
        $primary=Assert-LaTeXAIExperimentFreeze -Reference $spec.freeze -Article $assignment.Assignment.article
        foreach($reference in $conditionFreezes.Values){if($reference.sha256 -cne $spec.freeze.sha256){$null=Assert-LaTeXAIExperimentFreeze $reference $assignment.Assignment.article}}
        return $primary
    }
    finally{$watch.Stop();$script:validationMs+=$watch.Elapsed.TotalMilliseconds}
}
[void][IO.Directory]::CreateDirectory($paperDirectory)
Publish-Paper
try{
    if($paired){
        $frozen=Test-FrozenInputs
        if($frozen.Freeze.engine -cne $EngineRoot -or $frozen.Freeze.perl -cne $PerlPath){throw 'Runtime differs from frozen plan'}
        Set-LaTeXAIFrozenEnvironment $frozen.Freeze
        if($contrast){foreach($requested in $spec.conditions){if($requested.Contains('freeze')){$conditionFreezes[$requested.freeze.sha256]=$requested.freeze}}}
    }
    for($index=0;$index -lt $spec.conditions.Count;$index++){
        $requested=$spec.conditions[$index]
        $conditions[$index].status='running'
        $conditions[$index].execution.outcome='running'
        Publish-Paper
        if($requested.Contains('legacy')){
            try{
                $converted=Measure-LaTeXAILegacyCondition $requested $assignment.Assignment.article (Join-Path $paperDirectory "conditions/$($requested.id)")
                $conditions[$index]=$converted.Condition
                foreach($artifact in $converted.Artifacts){$artifacts.Add($artifact)}
                $imports.Add($converted)
            }catch{
                $conditions[$index].status='failed';$conditions[$index].execution.outcome='not-started'
                $conditions[$index].details.importError=$_.Exception.Message
            }
            Publish-Paper
            continue
        }
        $conditionFrozen=$frozen
        $parameters=$assignment.Plan.workerParameters
        if($contrast){
            $watch=[Diagnostics.Stopwatch]::StartNew()
            try{$conditionFrozen=Assert-LaTeXAIExperimentFreeze $requested.freeze $assignment.Assignment.article}
            finally{$validationMs+=$watch.Elapsed.TotalMilliseconds}
            $parameters=@{};foreach($key in $assignment.Plan.workerParameters.Keys){$parameters[$key]=$assignment.Plan.workerParameters[$key]}
            $parameters.IncludeStyles=$requested.includeStyles
            Set-LaTeXAIFrozenEnvironment $conditionFrozen.Freeze
        }
        $nativeArgs=@($LatexmlArgument)
        if($paired){$nativeArgs=@($requested.arguments)}
        $invoke=@{Article=$Article;OutDirectory=(Join-Path $paperDirectory "conditions/$($requested.id)")
            EngineRoot=$EngineRoot;SourceTree=($paired ? $frozen.Source.tree.root : $SourceTree);Entrypoint=$Entrypoint
            TreeSha256=$TreeSha256;PerlPath=$PerlPath;EngineVersion=$EngineVersion;EngineCommit=$EngineCommit
            Preload=$Preload;SearchPath=$SearchPath;IncludeStyles=$IncludeStyles;LatexmlArgument=$nativeArgs;Kpsewhich=$Kpsewhich
            TimeoutSeconds=$TimeoutSeconds;ConversionWorkingDirectory=$ConversionWorkingDirectory;ConditionId=$requested.id
            SamplePeakWorkingSet=$paired}
        if($contrast){
            $invoke.EngineRoot=$conditionFrozen.Freeze.engine;$invoke.PerlPath=$conditionFrozen.Freeze.perl
            $invoke.SourceTree=$conditionFrozen.Source.tree.root;$invoke.IncludeStyles=$parameters.IncludeStyles
            $invoke.EngineCommit=$conditionFrozen.Freeze.engineCommit+($conditionFrozen.Freeze.engineDirty.Count ? '+dirty' : '')
            $invoke.EngineVersion=''
            $conditions[$index].engine=@{root=$invoke.EngineRoot;version='';commit=$invoke.EngineCommit}
        }
        $reused=$null;$reason='Fresh conversion requested';$identity=$null
        if($paired){
            $watch=[Diagnostics.Stopwatch]::StartNew()
            try{$identity=Get-LaTeXAIConversionIdentity $conditionFrozen.Freeze $assignment.Assignment.article $parameters $requested}
            finally{$validationMs+=$watch.Elapsed.TotalMilliseconds}
            if($spec.Contains('reuse')){
                $watch=[Diagnostics.Stopwatch]::StartNew()
                try{$reused=Get-LaTeXAIRetainedCondition $spec.reuse $assignment.Assignment.article $requested $identity;$reason='Verified retained conversion identity and raw artifacts'}
                catch{$reason=$_.Exception.Message}
                finally{$validationMs+=$watch.Elapsed.TotalMilliseconds}
            }
        }
        if($null -ne $reused){
            $converted=Measure-LaTeXAIRetainedCondition $reused $assignment.Assignment.article $invoke.OutDirectory
            $retained.Add($reused)
        }elseif($spec.Contains('reuse') -and $spec.reuse.mode -ceq 'analysis-only'){
            $conditions[$index].status='failed'
            $conditions[$index].execution.outcome='not-started'
            $conditions[$index].conversion=@{action='rejected';identity=$identity.Identity;sha256=$identity.Sha256;reason=$reason;nativeDurationMs=0}
            Publish-Paper
            continue
        }else{$converted=Invoke-LaTeXAICondition @invoke}
        if($paired){
            $converted.Condition.conversion=@{action=($reused ? 'reused' : 'executed');identity=$identity.Identity;sha256=$identity.Sha256;reason=$reason
                nativeDurationMs=($reused ? $reused.Origin.nativeDurationMs : ($converted.Condition.counts.Contains('latexmlMs') ? $converted.Condition.counts.latexmlMs : 0))}
            if($reused){$converted.Condition.conversion.origin=$reused.Origin}
            if($contrast){$converted.Condition.conversion.freeze=$requested.freeze}
        }
        $conditions[$index]=$converted.Condition
        foreach($artifact in $converted.Artifacts){$artifacts.Add($artifact)}
        Publish-Paper
        if($paired){$null=Test-FrozenInputs}
        if($converted.Condition.execution.cleanupComplete -eq $false){$problems.Add('Native cleanup incomplete; remaining conditions were not started');break}
    }
    if($paired){
        Set-LaTeXAIFrozenEnvironment $frozen.Freeze
        foreach($edge in $spec.comparisons){
            $directory=Join-Path $paperDirectory "comparisons/$($edge.id)"
            $requestPath=Join-Path $paperDirectory "comparisons/$($edge.id).request.json"
            $left=@($conditions|Where-Object {$_.id -ceq $edge.left})[0]
            $right=@($conditions|Where-Object {$_.id -ceq $edge.right})[0]
            $request=@{schema='latexai/paper-comparison-request/1';mode=$edge.mode;article=$assignment.Assignment.article
                source=$frozen.Source.tree.root;paperDirectory=$paperDirectory;experiment=$assignment.Experiment;freeze=$spec.freeze;model=$spec.model
                left=@{condition=$left;artifacts=@($artifacts|Where-Object {$_.path.StartsWith("conditions/$($edge.left)/")})}
                right=@{condition=$right;artifacts=@($artifacts|Where-Object {$_.path.StartsWith("conditions/$($edge.right)/")})}}
            $null=Write-LaTeXAIFrozenJson $requestPath $request
            $stdout=Join-Path $paperDirectory "comparisons/$($edge.id).stdout.txt"
            $stderr=Join-Path $paperDirectory "comparisons/$($edge.id).stderr.txt"
            $run=Invoke-LaTeXAINative -FilePath $PerlPath -WorkingDirectory $EngineRoot -TimeoutSeconds $spec.comparisonTimeoutSeconds `
                -Arguments @('-I',(Join-Path $EngineRoot 'lib'),(Join-Path $EngineRoot 'tools/dev/compare-paper.pl'),$requestPath,$directory) `
                -StdOutPath $stdout -StdErrPath $stderr -SamplePeakWorkingSet
            $verdict='incomplete';$edgeIssues=@("Comparison process $($run.Outcome), exit $($run.ExitCode)")
            $reportPath=Join-Path $directory 'comparison.json'
            if($run.Outcome -eq 'exited' -and $run.CleanupComplete -and (Test-Path -LiteralPath $reportPath)){
                $report=Get-Content -LiteralPath $reportPath -Raw|ConvertFrom-Json -AsHashtable
                $expectedExit=@{pass=0;fail=1;incomplete=2}
                if($report.schema -ceq 'latexai/paper-comparison/1' -and $report.left -ceq $edge.left -and $report.right -ceq $edge.right -and
                    $expectedExit.ContainsKey($report.status) -and $run.ExitCode -eq $expectedExit[$report.status]){
                    $verdict=$report.status;$edgeIssues=@($report.issues)
                }
            }
            foreach($file in @($requestPath,$stdout,$stderr)){Add-PaperArtifact $file}
            if(Test-Path -LiteralPath $directory){foreach($file in Get-ChildItem -LiteralPath $directory -File -Recurse){Add-PaperArtifact $file.FullName}}
            $comparisons.Add(@{id=$edge.id;left=$edge.left;right=$edge.right;mode=$edge.mode;required=$edge.required;status=$verdict
                report=($(if(Test-Path -LiteralPath $reportPath){[IO.Path]::GetRelativePath($paperDirectory,$reportPath).Replace('\','/')}else{$null}))
                process=@{outcome=$run.Outcome;exitCode=$run.ExitCode;timedOut=$run.TimedOut;cleanupComplete=$run.CleanupComplete
                    peakWorkingSetBytes=$run.PeakWorkingSetBytes;memoryMethod='sampled-process-PeakWorkingSet64'}
                durationMs=$run.DurationMs;issues=$edgeIssues})
            Publish-Paper
        }
        $null=Test-FrozenInputs
        foreach($input in $retained){
            $watch=[Diagnostics.Stopwatch]::StartNew()
            try{
                $null=Read-LaTeXAIPinnedJson $input.Origin.record
                $null=Read-LaTeXAIPinnedJson $input.Origin.freeze
                $verified=Get-LaTeXAIConversionIdentity $input.Freeze $input.Article $input.Parameters $input.Declaration
                if($verified.Sha256 -cne $input.Identity.Sha256){throw 'Retained conversion implementation changed during analysis'}
                Assert-LaTeXAIRetainedConversionInputs $input.Freeze $input.Identity.Source
                foreach($file in $input.Raw){if((Get-InventoryFileReference $file.path).sha256 -cne $file.sha256){throw 'Retained artifact changed during analysis'}}
            }finally{$validationMs+=$watch.Elapsed.TotalMilliseconds}
        }
        foreach($input in $imports){
            $watch=[Diagnostics.Stopwatch]::StartNew()
            try{$null=Assert-LaTeXAILegacyPins $input.Import $input.Row}
            finally{$validationMs+=$watch.Elapsed.TotalMilliseconds}
        }
    }
    Publish-Paper -Terminal
}catch{
    $problems.Add($_.Exception.Message)
    foreach($edge in $spec.comparisons){
        if(@($comparisons|Where-Object {$_.id -ceq $edge.id}).Count){continue}
        $comparisons.Add(@{id=$edge.id;left=$edge.left;right=$edge.right;mode=$edge.mode;required=$edge.required;status='incomplete'
            report=$null;process=@{outcome='not-started';exitCode=$null;timedOut=$null;cleanupComplete=$null}
            durationMs=0;issues=@('Paper execution stopped before this comparison completed')})
    }
    if(-not $terminalWritten){Publish-Paper -Terminal}
    throw
}
if(@($conditions|Where-Object {$_.status -ne 'ok'}).Count -or $problems.Count -or @($comparisons|Where-Object {$_.status -eq 'incomplete'}).Count){
    throw "Paper experiment failed: conditions=$($conditions.status -join ','); comparisons=$($comparisons.status -join ','); $($problems -join '; ')"
}
