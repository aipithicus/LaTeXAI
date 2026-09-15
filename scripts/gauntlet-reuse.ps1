#requires -Version 7.5
# Stage identities and explicit import of frozen paper-record evidence.
function Read-LaTeXAIPinnedJson {
    param([System.Collections.IDictionary]$Reference)
    if((Get-InventoryFileReference $Reference.path).sha256 -cne $Reference.sha256){throw "Changed retained record: $($Reference.path)"}
    return (Get-Content -LiteralPath $Reference.path -Raw | ConvertFrom-Json -AsHashtable -DateKind String)
}

function Get-LaTeXAIIdentityHash {
    param([object]$Value)
    function Encode-Identity($Item) {
        if($Item -is [Collections.IDictionary]){
            $keys=[string[]]@($Item.Keys);[Array]::Sort($keys,[StringComparer]::Ordinal)
            return '{'+(@($keys|ForEach-Object {(ConvertTo-Json -InputObject $_ -Compress)+':'+(Encode-Identity $Item[$_])}) -join ',')+'}'
        }
        if($Item -is [array]){return '['+(@($Item|ForEach-Object {Encode-Identity $_}) -join ',')+']'}
        return (ConvertTo-Json -InputObject $Item -Depth 100 -Compress)
    }
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes((Encode-Identity $Value)))).ToLowerInvariant()
}

function Get-LaTeXAIConversionIdentity {
    param([System.Collections.IDictionary]$Freeze,[System.Collections.IDictionary]$Article,
        [System.Collections.IDictionary]$Parameters,[System.Collections.IDictionary]$Condition)
    $source=@($Freeze.sources|Where-Object {$_.article.directory -ceq $Article.directory})
    if($source.Count -ne 1 -or $source[0].tree.sha256 -cne $Article.treeSha256){throw 'Conversion source identity mismatch'}
    $inputs=[ordered]@{}
    foreach($relative in @('lib','bin','lib-ctan')){
        $root=Join-Path $Freeze.engine $relative
        $trees=@($Freeze.trees|Where-Object {$_.root -ceq $root})
        if($trees.Count -ne 1){throw "Missing engine tree: $relative"}
        $inputs[$relative]=$trees[0].sha256
    }
    foreach($relative in @('perl','c/bin')){
        $root=Join-Path $Freeze.perlRoot $relative
        $trees=@($Freeze.trees|Where-Object {$_.root -ceq $root})
        if($trees.Count -ne 1){throw "Missing runtime tree: $relative"}
        $inputs['runtime/'+$relative]=$trees[0].sha256
    }
    $files=@{}
    foreach($relative in @('scripts','tools/dev')){
        $tree=@($Freeze.trees|Where-Object {$_.root -ceq (Join-Path $Freeze.engine $relative)})[0]
        $manifest=Read-LaTeXAIPinnedJson $tree.manifest
        foreach($file in $manifest.files){$files[$relative+'/'+$file.path]=$file.sha256}
    }
    foreach($name in @('scripts/gauntlet-convert.ps1','scripts/latexai-common.ps1','scripts/gauntlet-freeze.ps1','scripts/policy.psd1')){
        if((Get-InventoryFileReference (Join-Path $Freeze.engine $name)).sha256 -cne $files[$name]){throw "Changed recorded conversion implementation: $name"}
    }
    foreach($name in @('scripts/native/NativeProcess.cs','scripts/kpsewhich.cmd','tools/dev/kpsewhich.pl')+@($files.Keys|Where-Object {$_ -like 'scripts/preloads/*'}|Sort-Object)){
        if(-not $files.ContainsKey($name)){throw "Missing conversion input: $name"}
        $path=Join-Path $Freeze.engine $name
        if((Get-InventoryFileReference $path).sha256 -cne $files[$name]){throw "Changed conversion input: $name"}
        $inputs[$name]=$files[$name]
    }
    $nativePolicy=Import-PowerShellDataFile (Join-Path $Freeze.engine 'scripts/policy.psd1')
    $inputs.nativePolicy=$nativePolicy.Direct
    # Only the conversion portion of the former combined driver is part of this
    # identity. This also imports the frozen paired-plan/1 checkpoint explicitly.
    # Inspection helpers and comparator code have independent stage identities.
    $convert=[IO.File]::ReadAllText((Join-Path $Freeze.engine 'scripts/gauntlet-convert.ps1')).Replace([string][char]13,'')
    $first=$convert.IndexOf('$stores =')
    $last=$convert.IndexOf('$nativeResult = $run',$first)
    if($first -lt 0 -or $last -le $first){throw 'Unrecognized conversion driver contract'}
    $inputs.invocation=Get-LaTeXAIIdentityHash $convert.Substring($first,$last-$first)
    foreach($file in @('gauntlet-convert.ps1','latexai-common.ps1','gauntlet-freeze.ps1')){
        $tokens=$null;$errors=$null
        $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Freeze.engine "scripts/$file"),[ref]$tokens,[ref]$errors)
        if($errors.Count){throw 'Invalid conversion implementation'}
        $names=switch($file){'gauntlet-convert.ps1'{@('Resolve-Perl','Invoke-Native')};'latexai-common.ps1'{@('Invoke-LaTeXAINative','Get-LaTeXAIPolicy')};'gauntlet-freeze.ps1'{@('Set-LaTeXAIFrozenEnvironment')}}
        foreach($name in $names){
            $functions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name},$true))
            if($functions.Count -ne 1){throw "Missing conversion function: $name"}
            $inputs[$name]=Get-LaTeXAIIdentityHash $functions[0].Extent.Text.Replace([string][char]13,'')
        }
    }
    $environment=@{}
    foreach($key in $Freeze.effectiveEnvironment.Keys){
        $environment[$key]=([string]$Freeze.effectiveEnvironment[$key]).Replace($Freeze.perlRoot,'<runtime>')
    }
    $options=[ordered]@{}
    foreach($name in @('IncludeStyles','SearchPath','Preload','Kpsewhich','TimeoutSeconds','ConversionWorkingDirectory')){
        $options[$name]=if($Parameters.Contains($name)){$Parameters[$name]}elseif($name -in @('SearchPath','Preload')){@()}else{$null}
    }
    $options.arguments=@($Condition.arguments)
    $identity=[ordered]@{schema='latexai/conversion-identity/1';engine=$inputs;source=$Article.treeSha256;entrypoint=$Article.entrypoint
        options=$options;environment=$environment;environmentPolicy=$Freeze.environmentPolicy
        powershell=$Freeze.powershell.sha256;hostRuntime=@{os=$Freeze.host.os;dotnet=$Freeze.host.dotnet};memoryMethod='sampled-process-PeakWorkingSet64'}
    return [pscustomobject]@{Identity=$identity;Sha256=(Get-LaTeXAIIdentityHash $identity);Source=$source[0]}
}

function Assert-LaTeXAIRetainedConversionInputs {
    param([System.Collections.IDictionary]$Freeze,[System.Collections.IDictionary]$Source)
    $roots=@('lib','bin','lib-ctan'|ForEach-Object {Join-Path $Freeze.engine $_})+@('perl','c/bin'|ForEach-Object {Join-Path $Freeze.perlRoot $_})
    foreach($tree in @($Freeze.trees|Where-Object {$_.root -cin $roots})+@($Source.tree)){
        $null=Read-LaTeXAIPinnedJson $tree.manifest
        if((Get-LaTeXAITreeRecord $tree.root).sha256 -cne $tree.sha256){throw "Changed retained conversion tree: $($tree.root)"}
    }
    if((Get-InventoryFileReference $Source.entrypoint.path).sha256 -cne $Source.entrypoint.sha256){throw 'Changed retained entrypoint'}
}

function New-LaTeXAIReusePlan {
    param([string]$Directory,[switch]$AnalysisOnly)
    $batchRef=Get-InventoryFileReference (Join-Path $Directory 'batch.json')
    $batch=Read-LaTeXAIPinnedJson $batchRef
    Assert-InventoryRecord $batch
    if($batch.schema -cne 'codex-scientiae/inventory-batch/1' -or $batch.engine -cne 'latexai'){throw 'Reuse requires an explicit LaTeXAI paper-record batch'}
    $plan=Read-LaTeXAIPinnedJson $batch.experiment
    Assert-InventoryRecord $plan
    if($plan.specification.schema -cne 'latexai/paired-plan/1'){throw 'Reuse requires frozen paired-plan/1 evidence'}
    $null=Read-LaTeXAIPinnedJson $batch.executor
    $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach($assignment in $plan.assignments){if(-not $seen.Add($assignment.article.directory)){throw 'Duplicate retained paper assignment'}}
    return [pscustomobject]@{Plan=$plan;Specification=@{schema='latexai/reuse-plan/1';mode=($AnalysisOnly ? 'analysis-only' : 'selective');batch=$batchRef;experiment=$batch.experiment}}
}

function Get-LaTeXAIRetainedCondition {
    param([System.Collections.IDictionary]$Reuse,[System.Collections.IDictionary]$Article,
        [System.Collections.IDictionary]$Requested,[object]$Expected)
    $batch=Read-LaTeXAIPinnedJson $Reuse.batch
    $plan=Read-LaTeXAIPinnedJson $Reuse.experiment
    $assignments=@($plan.assignments|Where-Object {$_.article.directory -ceq $Article.directory})
    if($assignments.Count -ne 1){throw 'No unique retained paper assignment'}
    $assignment=$assignments[0]
    foreach($key in @('directory','slug','sourceTree','entrypoint','treeSha256')){if($assignment.article[$key] -cne $Article[$key]){throw "Changed paper input: $key"}}
    $rows=@($batch.records|Where-Object {$_.jobId -ceq $assignment.jobId -and $_.attemptId -ceq $assignment.attemptId -and $_.path -ceq $assignment.record})
    if($rows.Count -ne 1 -or $rows[0].state -notin @('complete','failed')){throw 'Retained paper has no terminal evidence'}
    $recordPath=Join-Path (Split-Path $Reuse.batch.path) $assignment.record
    $recordRef=@{path=$recordPath;sha256=$rows[0].sha256}
    $null=Read-LaTeXAIPinnedJson $recordRef
    $read=Read-PaperRun -Path $recordPath -Assignment $assignment -Experiment $Reuse.experiment -MetadataOnly
    $paper=$read.Record
    if($paper.status -cne $rows[0].state -or $paper.producer.worker.sha256 -cne $plan.worker.sha256){throw 'Retained worker disagrees with batch'}
    $conditions=@($paper.payload.conditions|Where-Object {$_.id -ceq $Requested.id})
    $declarations=@($plan.specification.conditions|Where-Object {$_.id -ceq $Requested.id})
    if($conditions.Count -ne 1 -or $declarations.Count -ne 1){throw 'No unique retained condition'}
    $condition=$conditions[0]
    if($condition.status -cne 'ok' -or $condition.execution.outcome -cne 'exited' -or $condition.execution.exitCode -ne 0 -or
        $condition.execution.timedOut -ne $false -or $condition.execution.cleanupComplete -ne $true){throw 'Retained conversion did not complete successfully'}
    # A reused condition keeps the original conversion's freeze and invocation.
    $originFreeze=if($condition.Contains('conversion') -and $condition.conversion.action -eq 'reused'){$condition.conversion.origin.freeze}else{$paper.payload.freeze}
    $freeze=Read-LaTeXAIPinnedJson $originFreeze
    $identity=Get-LaTeXAIConversionIdentity $freeze $assignment.article $plan.workerParameters $declarations[0]
    if($identity.Sha256 -cne $Expected.Sha256){throw 'Conversion identity changed (source, engine, runtime, options or native instrumentation)'}
    Assert-LaTeXAIRetainedConversionInputs $freeze $identity.Source
    $directory=Split-Path $recordPath
    $raw=[Collections.Generic.List[object]]::new()
    foreach($name in @("$($Article.slug).xml",'latexml.log','latexml.stdout.txt','latexml.stderr.txt')){
        $relative="conditions/$($Requested.id)/$name"
        $matches=@($paper.artifacts|Where-Object {$_.path -ceq $relative})
        if($matches.Count -ne 1){throw "Missing retained raw artifact: $relative"}
        $path=Join-Path $directory $relative
        if((Get-InventoryFileReference $path).sha256 -cne $matches[0].sha256 -or (Get-Item -LiteralPath $path).Length -ne $matches[0].bytes){throw "Changed retained artifact: $relative"}
        $raw.Add(@{path=$path;name=$name;sha256=$matches[0].sha256;bytes=$matches[0].bytes})
    }
    if($condition.outputs.xml -cne "conditions/$($Requested.id)/$($Article.slug).xml" -or
        $condition.engine.root -cne $freeze.engine -or $condition.details.perl -cne $freeze.perl -or
        $condition.details.sourceTree -cne $identity.Source.tree.root){throw 'Retained conversion addresses disagree with frozen evidence'}
    $job=$condition.details.conversionWorkingDirectory
    $args=@('-I',(Join-Path $freeze.engine 'lib'),(Join-Path $freeze.engine 'bin/latexml'))
    if($plan.workerParameters.IncludeStyles){$args+='--includestyles'}
    $args+="--path=$($identity.Source.tree.root)"
    foreach($path in $plan.workerParameters.SearchPath){$args+='--path='+(Join-Path $freeze.engine $path)}
    foreach($preload in @($identity.Identity.options.Preload)){$args+="--preload=$preload"}
    $args+=@($declarations[0].arguments)
    $args+=@("--log=$(Join-Path $job 'latexml.log')","--destination=$(Join-Path $job ($Article.slug+'.xml'))",(Join-Path $identity.Source.tree.root $Article.entrypoint))
    if((Get-LaTeXAIIdentityHash $args) -cne (Get-LaTeXAIIdentityHash @($condition.details.arguments))){throw 'Retained invocation disagrees with declared options'}
    return [pscustomobject]@{Condition=$condition;Identity=$identity;Freeze=$freeze;Raw=$raw.ToArray();Parameters=$plan.workerParameters;Declaration=$declarations[0];Article=$assignment.article
        Origin=@{record=$recordRef;condition=$Requested.id;experiment=$Reuse.experiment;freeze=$originFreeze
            nativeDurationMs=($condition.Contains('conversion') ? $condition.conversion.nativeDurationMs : $condition.counts.latexmlMs)
            memory=($condition.Contains('conversion') -and $condition.conversion.action -eq 'reused' ? $condition.conversion.origin.memory : $condition.memory)}}
}

function Measure-LaTeXAIRetainedCondition {
    param([object]$Retained,[System.Collections.IDictionary]$Article,[string]$Directory)
    $started=[datetime]::UtcNow
    [void][IO.Directory]::CreateDirectory($Directory)
    foreach($file in $Retained.Raw){
        $target=Join-Path $Directory $file.name
        [IO.File]::Copy($file.path,$target,$false)
        if((Get-InventoryFileReference $target).sha256 -cne $file.sha256){throw 'Retained artifact changed during copy'}
    }
    $old=$Retained.Condition
    $run=[pscustomobject]@{Outcome=$old.execution.outcome;ExitCode=$old.execution.exitCode;TimedOut=$old.execution.timedOut
        CleanupComplete=$old.execution.cleanupComplete;DurationMs=0.0
        StdOut=[IO.File]::ReadAllText((Join-Path $Directory 'latexml.stdout.txt'));StdErr=[IO.File]::ReadAllText((Join-Path $Directory 'latexml.stderr.txt'))}
    try {
        $measured=Measure-LaTeXAICondition -Article $Article.directory -OutDirectory $Directory -EngineRoot $old.engine.root -SourceTree $old.details.sourceTree -Perl $old.details.perl -Arguments $old.details.arguments -ConversionCwd $old.details.conversionWorkingDirectory -Run $run -StartedUtc $started
    } catch {
        $measured=[pscustomobject]@{Status='failed';Counts=@{latexmlMs=0};Details=@{measurementError=$_.Exception.Message;perl=$old.details.perl;arguments=$old.details.arguments;conversionWorkingDirectory=$old.details.conversionWorkingDirectory}}
    }
    $measured.Details.sourceTree=$old.details.sourceTree
    $condition=@{id=$old.id;status=$measured.Status;engine=$old.engine;execution=$old.execution;outputs=$old.outputs
        counts=$measured.Counts;details=$measured.Details;durationMs=([datetime]::UtcNow-$started).TotalMilliseconds;memory=@{method='unavailable';bytes=$null}}
    $artifacts=@($Retained.Raw|ForEach-Object {@{path="conditions/$($old.id)/$($_.name)";sha256=$_.sha256;bytes=$_.bytes}})
    return [pscustomobject]@{Condition=$condition;Artifacts=$artifacts}
}
