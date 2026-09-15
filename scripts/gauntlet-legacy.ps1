#requires -Version 7.5
# Historical receipt import is analysis-only. No old file is rewritten.
function New-LaTeXAILegacyImport {
    param([System.Collections.IDictionary]$Request,[object[]]$Jobs)
    if($Request.rule -cne 'receipt-native-fields/1'){throw 'Unknown legacy import rule'}
    $root=(Resolve-Path -LiteralPath $Request.directory).Path
    $batch=Get-InventoryFileReference (Join-Path $root 'run.json')
    $run=Read-LaTeXAIPinnedJson $batch
    if($run.schema -cne 'codex-scientiae/inventory-run/0.1' -or $run.engine -cne 'latexai'){throw 'Expected legacy LaTeXAI inventory-run/0.1'}
    $receipts=@{}
    foreach($file in Get-ChildItem -LiteralPath (Join-Path $root 'jobs') -Filter receipt.json -File -Recurse){
        $reference=Get-InventoryFileReference $file.FullName
        $receipt=Read-LaTeXAIPinnedJson $reference
        if($receipt.schema -cne 'codex-scientiae/inventory-receipt/0.1' -or $receipt.engine -cne 'latexai'){throw 'Invalid legacy receipt'}
        $key=$receipt.article.directory
        if($receipts.ContainsKey($key)){throw 'Duplicate legacy paper receipt'}
        $receipts[$key]=@{reference=$reference;record=$receipt}
    }
    $papers=@(foreach($job in $Jobs){
        $article=$job.Metadata.ArticleIdentity
        $row=@{article=$article;receipt=$null;raw=@()}
        if($receipts.ContainsKey($article.directory)){
            $found=$receipts[$article.directory];$row.receipt=$found.reference
            $directory=Split-Path $found.reference.path
            $row.raw=@(foreach($name in @("$($article.slug).xml",'latexml.log','latexml.stdout.txt','latexml.stderr.txt')){
                $path=Join-Path $directory $name
                if(Test-Path -LiteralPath $path -PathType Leaf){@{name=$name;path=$path;sha256=(Get-InventoryFileReference $path).sha256;bytes=(Get-Item -LiteralPath $path).Length}}
            })
        }
        $row
    })
    return @{schema='latexai/legacy-import/1';rule=$Request.rule;batch=$batch;papers=$papers
        coverage=@{historicalJobs=$run.jobs;receiptsFound=$receipts.Count;selected=$papers.Count}
        limitations=@('Original engine/runtime bytes and peak memory were not frozen by the receipt contract; no conversion reuse identity is asserted.')}
}

function Assert-LaTeXAILegacyPins {
    param([System.Collections.IDictionary]$Import,[System.Collections.IDictionary]$Row)
    $null=Read-LaTeXAIPinnedJson $Import.batch
    if($null -eq $Row.receipt){throw 'Missing legacy receipt for assigned paper'}
    $receipt=Read-LaTeXAIPinnedJson $Row.receipt
    foreach($file in $Row.raw){
        if((Get-InventoryFileReference $file.path).sha256 -cne $file.sha256 -or (Get-Item -LiteralPath $file.path).Length -ne $file.bytes){throw 'Changed legacy raw artifact'}
    }
    foreach($key in @('directory','slug','treeSha256')){if($receipt.article[$key] -cne $Row.article[$key]){throw "Legacy paper identity changed: $key"}}
    if($receipt.entrypoint -cne $Row.article.entrypoint){throw 'Legacy entrypoint changed'}
    if((Get-LaTeXAITreeRecord $Row.article.sourceTree).sha256 -cne $Row.article.treeSha256){throw 'Legacy source bytes changed'}
    return $receipt
}

function Measure-LaTeXAILegacyCondition {
    param([System.Collections.IDictionary]$Requested,[System.Collections.IDictionary]$Article,[string]$Directory)
    $started=[datetime]::UtcNow
    $import=$Requested.legacy
    $rows=@($import.papers|Where-Object {$_.article.directory -ceq $Article.directory})
    if($rows.Count -ne 1){throw 'No unique legacy paper assignment'}
    $row=$rows[0];$old=Assert-LaTeXAILegacyPins $import $row
    $missing=@(@("$($Article.slug).xml",'latexml.log','latexml.stdout.txt','latexml.stderr.txt')|Where-Object {$_ -cnotin @($row.raw.name)})
    $nativeArguments=@($old.details.arguments)
    if($nativeArguments.Count -lt 5 -or $nativeArguments[0] -cne '-I'){throw 'Missing legacy invocation'}
    if(('--capture' -cin $nativeArguments) -ne $Requested.capture -or ('--includestyles' -cin $nativeArguments) -ne $Requested.includeStyles){throw 'Legacy invocation disagrees with declared capture/styles settings'}
    $engine=Split-Path $nativeArguments[1]
    $source=$Article.sourceTree
    $cwd=if($old.details.Contains('conversionWorkingDirectory')){$old.details.conversionWorkingDirectory}else{$source}
    $execution=@{outcome='unknown';exitCode=$null;timedOut=$null;cleanupComplete=$null}
    $rules=[Collections.Generic.List[string]]::new()
    if($missing.Count){$rules.Add('Missing legacy raw artifacts: '+($missing -join ', '))}
    if($old.details.Contains('nativeOutcome')){$execution.outcome=$old.details.nativeOutcome}
    if($old.counts.Contains('exitCode')){$execution.exitCode=$old.counts.exitCode}
    if($old.counts.Contains('timedOut')){$execution.timedOut=[bool]$old.counts.timedOut}
    elseif($execution.outcome -ceq 'exited'){$execution.timedOut=$false;$rules.Add('timedOut=false from this receipt nativeOutcome=exited')}
    if($old.details.Contains('nativeCleanupComplete')){$execution.cleanupComplete=$old.details.nativeCleanupComplete}
    $unknown=@($execution.Keys|Where-Object {$null -eq $execution[$_] -or ($execution[$_] -is [string] -and $execution[$_] -ceq 'unknown')})
    if($unknown.Count){$rules.Add('Unavailable execution fields: '+($unknown -join ', '))}
    if(-not $old.details.Contains('conversionWorkingDirectory')){$rules.Add('Missing cwd interpreted as article source under inventory-receipt/0.1 invocation contract')}
    [void][IO.Directory]::CreateDirectory($Directory)
    foreach($file in $row.raw){
        $target=Join-Path $Directory $file.name
        [IO.File]::Copy($file.path,$target,$false)
        if((Get-InventoryFileReference $target).sha256 -cne $file.sha256){throw 'Legacy input changed during copy'}
    }
    $run=[pscustomobject]@{Outcome=$execution.outcome;ExitCode=$execution.exitCode;TimedOut=$execution.timedOut
        CleanupComplete=$execution.cleanupComplete;DurationMs=0;StdOut='';StdErr=''}
    $measured=Measure-LaTeXAICondition -Article $Article.directory -OutDirectory $Directory -EngineRoot $engine -SourceTree $source `
        -Perl $old.details.perl -Arguments $nativeArguments -ConversionCwd $cwd -Run $run -StartedUtc $started -HistoricalEvidence
    $measured.Details.sourceTree=$source
    foreach($key in @('exitCode','timedOut')){if($null -eq $execution[$key]){$measured.Counts.Remove($key)}}
    $measured.Details.nativeOutcome=$execution.outcome;$measured.Details.nativeExitCode=$execution.exitCode;$measured.Details.nativeCleanupComplete=$execution.cleanupComplete
    $origin=@{rule=$import.rule;batch=$import.batch;receipt=$row.receipt;raw=$row.raw;appliedRules=$rules.ToArray();limitations=$import.limitations
        nativeDurationMs=($old.counts.Contains('latexmlMs') ? $old.counts.latexmlMs : $null)
        memory=@{method='unavailable';bytes=$null};invocationContract=($old.details.Contains('conversionWorkingDirectory') ? 'recorded-cwd' : 'receipt-source-cwd')}
    $outputs=@{}
    if("$($Article.slug).xml" -cin @($row.raw.name)){$outputs.xml="conditions/$($Requested.id)/$($Article.slug).xml"}
    $admitted=$old.status -ceq 'ok' -and -not $missing.Count -and -not $unknown.Count -and $execution.outcome -ceq 'exited' -and
        $execution.exitCode -eq 0 -and $execution.timedOut -eq $false -and $execution.cleanupComplete -eq $true
    $condition=@{id=$Requested.id;status=($admitted ? $measured.Status : 'failed');engine=@{root=$engine;version=$old.engineVersion;commit=$old.engineCommit}
        execution=$execution;outputs=$outputs;counts=$measured.Counts;details=$measured.Details
        durationMs=([datetime]::UtcNow-$started).TotalMilliseconds;memory=@{method='unavailable';bytes=$null};legacy=$origin}
    return [pscustomobject]@{Condition=$condition;Artifacts=@($row.raw|ForEach-Object {@{path="conditions/$($Requested.id)/$($_.name)";sha256=$_.sha256;bytes=$_.bytes}});Import=$import;Row=$row}
}
