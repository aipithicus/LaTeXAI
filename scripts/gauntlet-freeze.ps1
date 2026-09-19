#requires -Version 7.5
# Content snapshots for a declared experiment; paths alone are not input pins.
function Get-LaTeXAITreeRecord {
    param([Parameter(Mandatory)][string]$Root)
    $rootPath=(Resolve-Path -LiteralPath $Root).Path
    if(-not ('LaTeXAI.TreeFingerprint' -as [type])){
        Add-Type -Path (Join-Path $PSScriptRoot 'native/TreeFingerprint.cs') -ErrorAction Stop
    }
    $tree=[LaTeXAI.TreeFingerprint]::Read($rootPath)
    $files=@($tree.Files|ForEach-Object {@{path=$_.Path;bytes=$_.Bytes;sha256=$_.Sha256}})
    return [ordered]@{root=$rootPath;sha256=$tree.Sha256;count=$files.Count;files=$files}
}

function Write-LaTeXAIFrozenJson {
    param([string]$Path,[object]$Value)
    if(Test-Path -LiteralPath $Path){throw "Frozen input already exists: $Path"}
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path))
    [IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 100)+"`n",[Text.UTF8Encoding]::new($false))
    return (Get-InventoryFileReference $Path)
}

function Copy-LaTeXAIInputTree {
    param([string]$Source,[string]$Destination,[string]$Manifest)
    if(Test-Path -LiteralPath $Destination){throw "Input copy already exists: $Destination"}
    $before=Get-LaTeXAITreeRecord $Source
    [void][IO.Directory]::CreateDirectory($Destination)
    foreach($file in $before.files){
        $target=Join-Path $Destination $file.path
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
        [IO.File]::Copy((Join-Path $Source $file.path),$target,$false)
    }
    $after=Get-LaTeXAITreeRecord $Destination
    if($before.sha256 -cne $after.sha256 -or $before.sha256 -cne (Get-LaTeXAITreeRecord $Source).sha256){throw "Input changed during copy: $Source"}
    return [ordered]@{origin=[IO.Path]::GetFullPath($Source);root=$after.root;sha256=$after.sha256;count=$after.count;manifest=(Write-LaTeXAIFrozenJson $Manifest $after)}
}

function New-LaTeXAIExperimentFreeze {
    param([string]$Directory,[string]$EngineRoot,[string]$PerlRoot,[string]$CdxsciRoot,[object[]]$Jobs,[string]$PowerShellExecutable)
    if(Test-Path -LiteralPath $Directory){throw "Choose a new freeze directory: $Directory"}
    $watch=[Diagnostics.Stopwatch]::StartNew()
    [void][IO.Directory]::CreateDirectory($Directory)
    $trees=[Collections.Generic.List[object]]::new()
    $engine=Join-Path $Directory 'engine'
    # These are all runtime engine inputs, including generated modules and the
    # resident library. Reference-only lib-symb/lib-katex/lib-park are not read.
    foreach($name in @('lib','bin','scripts','tools/dev','lib-ctan')){
        $tree=Copy-LaTeXAIInputTree (Join-Path $EngineRoot $name) (Join-Path $engine $name) (Join-Path $Directory ('manifests/engine-'+$name.Replace('/','-')+'.json'))
        $trees.Add($tree)
    }
    $perlRootCopy=Join-Path $Directory 'runtime'
    foreach($name in @('perl','c/bin')){
        $trees.Add((Copy-LaTeXAIInputTree (Join-Path $PerlRoot $name) (Join-Path $perlRootCopy $name) (Join-Path $Directory ('manifests/runtime-'+$name.Replace('/','-')+'.json'))))
    }
    # Shared orchestration remains at its configured checkout; pin all execution
    # code and verify it before dispatch and during worker publication.
    foreach($name in @('src/batch-executor','src/batch-adapters','src/infrastructure','src/inventory-records','packages/batch-executor')){
        $tree=Get-LaTeXAITreeRecord (Join-Path $CdxsciRoot $name)
        $trees.Add(@{root=$tree.root;sha256=$tree.sha256;count=$tree.count;manifest=(Write-LaTeXAIFrozenJson (Join-Path $Directory ('manifests/shared-'+$name.Replace('/','-')+'.json')) $tree)})
    }
    $sources=[Collections.Generic.List[object]]::new()
    $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach($job in $Jobs){
        $article=$job.Metadata.ArticleIdentity
        if(-not $seen.Add($article.slug)){throw 'Duplicate frozen paper slug'}
        $tree=Copy-LaTeXAIInputTree $article.sourceTree (Join-Path $Directory "sources/$($article.slug)") (Join-Path $Directory "manifests/source-$($article.slug).json")
        if($tree.sha256 -cne $article.treeSha256){throw "Declared source-tree fingerprint mismatch: $($article.slug)"}
        $entry=[IO.Path]::GetFullPath((Join-Path $tree.root $article.entrypoint))
        if(-not $entry.StartsWith($tree.root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Entrypoint escapes frozen source'}
        $sources.Add(@{article=$article;tree=$tree;entrypoint=(Get-InventoryFileReference $entry)})
    }
    $git=(Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $commit=(& $git -C $EngineRoot rev-parse HEAD).Trim()
    if($LASTEXITCODE){throw 'Cannot identify engine commit'}
    $dirty=@(& $git -C $EngineRoot status --porcelain)
    & $git -C $EngineRoot diff --binary "--output=$(Join-Path $Directory 'engine.patch')" HEAD -- lib bin scripts tools/dev
    if($LASTEXITCODE){throw 'Cannot retain engine patch'}
    $environment=@{}
    foreach($entry in Get-ChildItem Env:){if($entry.Name -match '^(PERL|LATEX|TEX|BIB|LANG$|LC_|OMP_|OPENBLAS_|MKL_|PATH$|PATHEXT$)'){$environment[$entry.Name]=$entry.Value}}
    $effective=@{PERL_ROOT=$perlRootCopy;PERL_HOME=(Join-Path $perlRootCopy 'perl');PATH=((Join-Path $perlRootCopy 'perl/bin'),(Join-Path $perlRootCopy 'c/bin'),[Environment]::SystemDirectory -join ';')}
    $freeze=[ordered]@{
        schema='latexai/experiment-freeze/1';createdUtc=[datetime]::UtcNow.ToString('o');durationMs=$watch.Elapsed.TotalMilliseconds;engine=$engine;engineOrigin=$EngineRoot
        engineCommit=$commit;engineDirty=$dirty;enginePatch=(Get-InventoryFileReference (Join-Path $Directory 'engine.patch'))
        generatedVersion=(Get-InventoryFileReference (Join-Path $engine 'lib/LaTeXML/Version.pm'))
        perl=(Join-Path $perlRootCopy 'perl/bin/perl.exe');perlRoot=$perlRootCopy
        powershell=(Get-InventoryFileReference $PowerShellExecutable);batchRunner=(Get-InventoryFileReference (Join-Path $CdxsciRoot 'src/batch-runner.ps1'))
        trees=$trees.ToArray();sources=$sources.ToArray();originalEnvironment=$environment;effectiveEnvironment=$effective
        environmentPolicy='Clear PERL/LATEX/TEX/BIB and locale/BLAS overrides; set frozen runtime paths; preserve worker temp containment.'
        host=@{machine=$env:COMPUTERNAME;processors=[Environment]::ProcessorCount;os=[Environment]::OSVersion.VersionString;dotnet=[Runtime.InteropServices.RuntimeInformation]::FrameworkDescription}
    }
    return [pscustomobject]@{Record=$freeze;Reference=(Write-LaTeXAIFrozenJson (Join-Path $Directory 'freeze.json') $freeze)}
}

function Assert-LaTeXAIExperimentFreeze {
    param([System.Collections.IDictionary]$Reference,[System.Collections.IDictionary]$Article)
    if((Get-InventoryFileReference $Reference.path).sha256 -cne $Reference.sha256){throw 'Changed experiment freeze'}
    $freeze=Get-Content -LiteralPath $Reference.path -Raw | ConvertFrom-Json -AsHashtable -DateKind String
    if($freeze.schema -cne 'latexai/experiment-freeze/1'){throw 'Unknown experiment freeze'}
    foreach($pin in @($freeze.generatedVersion,$freeze.enginePatch,$freeze.powershell,$freeze.batchRunner)){
        if((Get-InventoryFileReference $pin.path).sha256 -cne $pin.sha256){throw "Changed frozen file: $($pin.path)"}
    }
    $source=@($freeze.sources|Where-Object {$_.article.directory -ceq $Article.directory})
    if($source.Count -ne 1){throw 'Missing or duplicate frozen source assignment'}
    foreach($key in $Article.Keys){if($source[0].article[$key] -cne $Article[$key]){throw "Frozen article identity mismatch: $key"}}
    foreach($tree in @($freeze.trees)+@($source[0].tree)){
        if((Get-InventoryFileReference $tree.manifest.path).sha256 -cne $tree.manifest.sha256 -or (Get-LaTeXAITreeRecord $tree.root).sha256 -cne $tree.sha256){throw "Changed frozen input tree: $($tree.root)"}
    }
    if((Get-InventoryFileReference $source[0].entrypoint.path).sha256 -cne $source[0].entrypoint.sha256){throw 'Changed frozen entrypoint'}
    return [pscustomobject]@{Freeze=$freeze;Source=$source[0]}
}

function Set-LaTeXAIFrozenEnvironment {
    param([System.Collections.IDictionary]$Freeze)
    foreach($entry in Get-ChildItem Env:){if($entry.Name -match '^(PERL|LATEX|TEX|BIB|LANG$|LC_|OMP_|OPENBLAS_|MKL_)'){[Environment]::SetEnvironmentVariable($entry.Name,$null)}}
    foreach($key in $Freeze.effectiveEnvironment.Keys){[Environment]::SetEnvironmentVariable($key,$Freeze.effectiveEnvironment[$key])}
}
