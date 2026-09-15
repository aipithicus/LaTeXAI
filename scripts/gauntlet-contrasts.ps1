#requires -Version 7.5
# Explicit condition graphs; the ordinary inventory runner still owns dispatch.
function Read-LaTeXAIContrastInput {
    param([string]$Path)
    $reference=Get-InventoryFileReference $Path
    $input=Read-LaTeXAIPinnedJson $reference
    $schema=Join-Path $PSScriptRoot 'schemas/contrast-input.schema.json'
    if(-not (Test-Json -Json ($input|ConvertTo-Json -Depth 100) -SchemaFile $schema)){throw 'Invalid contrast input'}
    $ids=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach($condition in $input.conditions){
        if(-not $ids.Add($condition.id)){throw 'Duplicate condition id'}
        if(-not $condition.Contains('arguments')){$condition.arguments=@()}
        if($condition.Contains('legacy') -and $condition.arguments.Count){throw 'Legacy arguments come from the pinned receipt and cannot be overridden'}
        foreach($flag in $condition.arguments){
            if($flag -notmatch '^--([a-z][a-z0-9-]*)$'){throw 'Contrast arguments must be standalone flags'}
            $option=$Matches[1]
            if(@('capture','nocapture','no-capture','includestyles','noincludestyles','path','log','destination','output','preload','preamble','postamble','init','inputencoding','debug','documentid')|
                Where-Object {$_.StartsWith($option,[StringComparison]::OrdinalIgnoreCase)}){throw 'Contrast capture, styles and file options are owned by the declaration'}
        }
        if($condition.capture){$condition.arguments+=@('--capture')}
        if($condition.Contains('engineRoot')){$condition.engineRoot=(Resolve-Path -LiteralPath $condition.engineRoot).Path}
    }
    $edges=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach($edge in $input.comparisons){
        if(-not $edges.Add($edge.id) -or -not $ids.Contains($edge.left) -or -not $ids.Contains($edge.right) -or $edge.left -ceq $edge.right){throw 'Invalid or duplicate comparison endpoints'}
        $left=@($input.conditions|Where-Object {$_.id -ceq $edge.left})[0]
        $right=@($input.conditions|Where-Object {$_.id -ceq $edge.right})[0]
        if($edge.mode -ceq 'parity'){
            if($left.capture -or -not $right.capture -or $left.includeStyles -ne $right.includeStyles){throw 'Parity requires capture off/on with the same style setting'}
        }elseif($left.capture -ne $right.capture){throw 'Regression and styles contrasts require the same capture setting'}
        if($edge.mode -ceq 'regression' -and $left.includeStyles -ne $right.includeStyles){throw 'Regression requires the same style setting'}
        if($edge.mode -ceq 'styles' -and ($left.includeStyles -or -not $right.includeStyles)){throw 'Styles requires includestyles off/on endpoints'}
    }
    return [pscustomobject]@{Reference=$reference;Input=$input}
}

function Get-LaTeXAIEngineRevision {
    param([string]$EngineRoot,[string]$PatchPath)
    $git=(Get-Command git -CommandType Application -ErrorAction Stop|Select-Object -First 1).Source
    $probe=Invoke-LaTeXAINative -FilePath $git -WorkingDirectory $EngineRoot -TimeoutSeconds 30 -Arguments @('rev-parse','--show-toplevel')
    if($probe.Outcome -ne 'exited' -or -not $probe.CleanupComplete){throw 'Engine revision probe did not complete'}
    $isCheckout=$probe.ExitCode -eq 0 -and [IO.Path]::GetFullPath($probe.StdOut.Trim()).TrimEnd('\','/') -ieq [IO.Path]::GetFullPath($EngineRoot).TrimEnd('\','/')
    if(-not $isCheckout){
        [IO.File]::WriteAllText($PatchPath,'',[Text.UTF8Encoding]::new($false))
        return [pscustomobject]@{Commit='unversioned';Dirty=@();Patch=(Get-InventoryFileReference $PatchPath)}
    }
    $commit=Invoke-LaTeXAINative -FilePath $git -WorkingDirectory $EngineRoot -TimeoutSeconds 30 -Arguments @('rev-parse','HEAD')
    $dirty=Invoke-LaTeXAINative -FilePath $git -WorkingDirectory $EngineRoot -TimeoutSeconds 30 -Arguments @('status','--porcelain')
    $patch=Invoke-LaTeXAINative -FilePath $git -WorkingDirectory $EngineRoot -TimeoutSeconds 30 -Arguments @('diff','--binary',"--output=$PatchPath",'HEAD','--','lib','bin','lib-ctan')
    foreach($result in @($commit,$dirty,$patch)){if($result.Outcome -ne 'exited' -or $result.ExitCode -ne 0 -or -not $result.CleanupComplete){throw 'Cannot retain engine revision evidence'}}
    return [pscustomobject]@{Commit=$commit.StdOut.Trim();Dirty=@($dirty.StdOut -split "`r?`n"|Where-Object {$_});Patch=(Get-InventoryFileReference $PatchPath)}
}

function New-LaTeXAIAlternateEngineFreeze {
    param([object]$Primary,[string]$EngineRoot,[string]$Directory)
    # All revisions use the same current instrumentation and preloads. Only the
    # three declared engine/library trees vary; their bytes are pinned separately.
    $record=$Primary.Record|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable -DateKind String
    $engine=Join-Path $Directory 'engine'
    $trees=[Collections.Generic.List[object]]::new()
    foreach($tree in $record.trees){if(-not $tree.root.StartsWith($record.engine+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){$trees.Add($tree)}}
    foreach($name in @('lib','bin','lib-ctan','scripts','tools/dev')){
        $origin=if($name -in @('scripts','tools/dev')){$Primary.Record.engine}else{$EngineRoot}
        $trees.Add((Copy-LaTeXAIInputTree (Join-Path $origin $name) (Join-Path $engine $name) (Join-Path $Directory ('manifests/'+$name.Replace('/','-')+'.json'))))
    }
    $record.engine=$engine;$record.engineOrigin=$EngineRoot;$record.trees=$trees.ToArray()
    $record.generatedVersion=Get-InventoryFileReference (Join-Path $engine 'lib/LaTeXML/Version.pm')
    $revision=Get-LaTeXAIEngineRevision $EngineRoot (Join-Path $Directory 'engine.patch')
    $record.engineCommit=$revision.Commit;$record.engineDirty=$revision.Dirty;$record.enginePatch=$revision.Patch
    $record.instrumentation=$Primary.Reference
    return [pscustomobject]@{Record=$record;Reference=(Write-LaTeXAIFrozenJson (Join-Path $Directory 'freeze.json') $record)}
}

function Complete-LaTeXAIContrastPlan {
    param([object]$Declaration,[object]$Primary,[object[]]$Jobs,[string]$Directory,[System.Collections.IDictionary]$Parameters)
    $engines=@{$Primary.Record.engineOrigin=$Primary}
    $conditions=[Collections.Generic.List[object]]::new()
    foreach($item in $Declaration.Input.conditions){
        $condition=$item|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable
        if($condition.Contains('legacy')){
            $condition.legacy=New-LaTeXAILegacyImport $condition.legacy $Jobs
        }else{
            $root=if($condition.Contains('engineRoot')){$condition.engineRoot}else{$Primary.Record.engineOrigin}
            if(-not $engines.ContainsKey($root)){$engines[$root]=New-LaTeXAIAlternateEngineFreeze $Primary $root (Join-Path $Directory $condition.id)}
            $condition.freeze=$engines[$root].Reference
            $condition.engineRoot=$engines[$root].Record.engine
        }
        $conditions.Add($condition)
    }
    return [pscustomobject]@{Conditions=$conditions.ToArray();Comparisons=$Declaration.Input.comparisons}
}
