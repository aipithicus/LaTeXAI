#requires -Version 7.5
# Inspect retained XML and native streams; this function starts no conversion.
function Measure-LaTeXAICondition {
param(
    [string]$Article, [string]$OutDirectory, [string]$EngineRoot, [string]$SourceTree,
    [string]$Perl, [string[]]$Arguments, [string]$ConversionCwd, [object]$Run,
    [datetime]$StartedUtc
)
$slug=[IO.Path]::GetFileName($Article.TrimEnd('\','/'))
$logPath=Join-Path $OutDirectory 'latexml.log'
$xmlPath=Join-Path $OutDirectory "$slug.xml"
$stdoutPath=Join-Path $OutDirectory 'latexml.stdout.txt'
$stderrPath=Join-Path $OutDirectory 'latexml.stderr.txt'
$nativeStderr=if(Test-Path -LiteralPath $stderrPath){[IO.File]::ReadAllText($stderrPath)}else{[string]$Run.StdErr}
$latexmlMs=[double]$Run.DurationMs
$stores=[Collections.Generic.List[string]]::new()
$script:DefinitionTextCache = @{}
$script:DefinitionCandidates = $null
function Get-LsRLookup {
    <# Bare file name -> lib-ctan entry from ls-R. Used when the route stem
       is not the CTAN-id directory (t1enc.def lives under latex). #>
    param([string] $LsRPath)
    $map = @{}
    if (-not (Test-Path -LiteralPath $LsRPath -PathType Leaf)) { return $map }
    $subdir = ''
    foreach ($line in [System.IO.File]::ReadAllLines($LsRPath)) {
        if ($line.Length -eq 0 -or $line[0] -eq '%') { continue }
        if ($line.EndsWith(':')) {
            $subdir = $line.Substring(0, $line.Length - 1)
            if ($subdir.StartsWith('./')) { $subdir = $subdir.Substring(2) }
            continue
        }
        $rel = if ($subdir -eq '' -or $subdir -eq '.') { $line } else { "$subdir/$line" }
        $map[$line] = ($rel -split '/')[0]
    }
    return $map
}

function Get-DefinitionCandidateFiles {
    <# Files that could define a macro: the paper's own tree, then the vendored CTAN
       source (lib-ctan/<pkg>/tex/**) of every package the paper routed through. #>
    param([string] $SourceTree, [string] $EngineRoot, [object[]] $Packages)
    $files = [System.Collections.Generic.List[object]]::new()
    $extensions = @('.tex', '.sty', '.cls', '.def', '.clo', '.ldf', '.cfg')
    foreach ($f in Get-ChildItem -LiteralPath $SourceTree -File -Recurse -ErrorAction SilentlyContinue) {
        if ($extensions -contains $f.Extension.ToLowerInvariant() -and $f.Length -lt 4MB) {
            $files.Add([pscustomobject]@{ Path = $f.FullName; Label = 'paper:' + $f.FullName.Substring($SourceTree.Length).TrimStart('\', '/') })
        }
    }
    $ctanRoot = Join-Path $EngineRoot 'lib-ctan'
    $lsrMap = Get-LsRLookup -LsRPath (Join-Path $ctanRoot 'ls-R')
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($package in $Packages) {
        $name = [string]$package.name
        $stem = [System.IO.Path]::GetFileNameWithoutExtension($name)
        $entry = $stem
        $texRoot = Join-Path (Join-Path $ctanRoot $stem) 'tex'
        if (-not (Test-Path -LiteralPath $texRoot -PathType Container)) {
            foreach ($key in @($name, "$stem.sty", "$stem.cls", "$stem.def", "$stem.tex")) {
                if ($lsrMap.ContainsKey($key)) { $entry = $lsrMap[$key]; break }
            }
            $texRoot = Join-Path (Join-Path $ctanRoot $entry) 'tex'
        }
        if (-not $entry -or -not $seen.Add($entry)) { continue }
        if (-not (Test-Path -LiteralPath $texRoot -PathType Container)) { continue }
        foreach ($f in Get-ChildItem -LiteralPath $texRoot -File -Recurse -ErrorAction SilentlyContinue) {
            if ($extensions -contains $f.Extension.ToLowerInvariant() -and $f.Length -lt 4MB) {
                $files.Add([pscustomobject]@{ Path = $f.FullName; Label = 'ctan:' + $entry + '/' + $f.Name })
            }
        }
    }
    return $files.ToArray()
}

function Find-DefinitionSource {
    <# Where a macro or environment the engine reported as undefined is defined, if any
       source in reach defines it. Returns 'paper:<file>', 'ctan:<pkg>/<file>', or 'none'. #>
    param([string] $Macro, [string] $SourceTree, [string] $EngineRoot, [object[]] $Packages)
    if (-not $script:DefinitionCandidates) {
        $script:DefinitionCandidates = Get-DefinitionCandidateFiles -SourceTree $SourceTree -EngineRoot $EngineRoot -Packages $Packages
    }
    $pattern = $null
    if ($Macro -match '^\{(.+)\}$') {
        $name = [regex]::Escape($matches[1])
        $pattern = '\\(?:[A-Za-z]*(?:environment|theorem|tcolorbox|tcbtheorem|mdenv|mdtheoremenv|TColorBox|DocumentEnvironment))\*?\s*(?:\[[^\]]*\])?\s*\{\s*' + $name + '\s*\}'
    }
    elseif ($Macro -match '^\\(.+)$') {
        $name = [regex]::Escape($matches[1])
        $pattern = '\\(?:(?:new|renew|provide)command\*?|(?:New|Renew|Provide|Declare)(?:Document|Expandable)?Command|DeclareRobustCommand\*?|DeclareMathOperator\*?|newcommandx\*?|[gex]?def|let|futurelet|DeclareTextCommand|DeclareTextSymbol|newif|newlength|newbox|newdimen|newcount|newtoks)\s*\{?\s*\\' + $name + '(?![A-Za-z@])'
    }
    if (-not $pattern) { return 'none' }
    $regex = [regex]::new($pattern)
    foreach ($candidate in $script:DefinitionCandidates) {
        if (-not $script:DefinitionTextCache.ContainsKey($candidate.Path)) {
            try { $script:DefinitionTextCache[$candidate.Path] = [System.IO.File]::ReadAllText($candidate.Path) }
            catch { $script:DefinitionTextCache[$candidate.Path] = '' }
        }
        if ($regex.IsMatch($script:DefinitionTextCache[$candidate.Path])) { return $candidate.Label }
    }
    return 'none'
}

function Get-CountFromStatus {
    param([string] $Line, [string] $Pattern)
    $match = [regex]::Match($Line, $Pattern)
    if ($match.Success) { return [int]$match.Groups[1].Value }
    return 0
}

function Get-ListFromStatus {
    param([string] $Line, [string] $Pattern)
    $match = [regex]::Match($Line, $Pattern)
    if (-not $match.Success) { return @() }
    return @($match.Groups[1].Value -split ',\s*' | Where-Object { $_ -ne '' })
}


    $logParseStarted = [datetime]::UtcNow

    # The log's last "Conversion complete|failed: ..." line carries the engine's own tally.
    # The rest of the log carries what that tally summarizes: every file the engine read
    # and how (a binding from lib/, or raw TeX definitions), and every diagnostic with
    # its severity, category, and object.
    $statusLine = ''
    $bindingLoads = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $rawLoads = [System.Collections.Generic.List[string]]::new()
    $taxonomy = @{}
    # With the lxprofile.sty preload (gauntlet-run.ps1 -Profile) the engine's macro
    # profiler prints "Profiling results:" followed by "Total calls: N; Maximum depth: D"
    # and four titled lists, each on the line after its title:
    #   Most frequent / Deepest   ->  \cs:count, ...
    #   Most expensive inclusive / exclusive  ->  \cs:1.23s/count, ...
    $profileTotals = $null
    $profileLists = @{}
    $profileTitle = ''
    if (Test-Path -LiteralPath $logPath -PathType Leaf) {
        foreach ($line in [System.IO.File]::ReadLines($logPath)) {
            if ($profileTitle) {
                $entries = [System.Collections.Generic.List[object]]::new()
                foreach ($item in ($line.Trim() -split ',\s+')) {
                    if ($item -match '^(.+):(\d+(?:\.\d+)?)s/(\d+)$') {
                        $entries.Add([ordered]@{ cs = $matches[1]; seconds = [double]$matches[2]; calls = [int]$matches[3] })
                    }
                    elseif ($item -match '^(.+):(\d+)$') {
                        $entries.Add([ordered]@{ cs = $matches[1]; count = [int]$matches[2] })
                    }
                }
                $profileLists[$profileTitle] = $entries.ToArray()
                $profileTitle = ''
                continue
            }
            if ($line -match '^Total calls: (\d+); Maximum depth: (\d+)') {
                $profileTotals = [ordered]@{ calls = [int]$matches[1]; maxDepth = [int]$matches[2] }
                continue
            }
            if ($line -match '^(Most frequent|Deepest|Most expensive inclusive|Most expensive exclusive)\s*:\s*$') {
                $profileTitle = switch ($matches[1]) {
                    'Most frequent' { 'frequent' }
                    'Deepest' { 'deepest' }
                    'Most expensive inclusive' { 'inclusive' }
                    'Most expensive exclusive' { 'exclusive' }
                }
                continue
            }
            if ($line -match '^(?:recursive )?Conversion (?:complete|failed):') { $statusLine = $line; continue }
            if ($line -match '^\(Loading (.+?)\.\.\.') {
                if ($matches[1] -match '[\\/]Package[\\/]([^\\/]+)\.ltxml$') { [void]$bindingLoads.Add($matches[1]) }
                continue
            }
            if ($line -match '^\(Processing definitions (.+?)\.\.\.') { $rawLoads.Add($matches[1]); continue }
            if ($line -match '^(Fatal|Error|Warning|Info):([A-Za-z_]+):(\S{0,80})') {
                $key = '{0}:{1}:{2}' -f $matches[1], $matches[2], $matches[3]
                $taxonomy[$key] = 1 + ($taxonomy.ContainsKey($key) ? [int]$taxonomy[$key] : 0)
            }
        }
    }
    # Phase timings from stderr. The engine prints "(Digesting TeX main..." then nested
    # "(Loading ...  0.01 sec)" groups, then its own "  6.70 sec)"; likewise "(Building",
    # "(Rewriting", "(Math Parsing N formulae", "(Finalizing". A stack pairs each close
    # with its open, so a phase's seconds include the loads it triggered.
    $phases = [ordered]@{}
    $phaseStack = [System.Collections.Generic.Stack[string]]::new()
    $phaseTokens = [regex]::Matches($nativeStderr,
        '\((Digesting TeX|Building|Rewriting|Math Parsing (\d+) formulae|Finalizing|Loading|Processing (?:definitions|content))\b|(?<![\w.])(\d+\.\d+) sec\)')
    foreach ($token in $phaseTokens) {
        if ($token.Groups[3].Success) {
            if ($phaseStack.Count -eq 0) { continue }
            $label = $phaseStack.Pop()
            if ($label -eq '') { continue }
            if ($label -like 'Math Parsing *') {
                $phases['formulae'] = [int]($label -split ' ')[2]
                $label = 'mathParse'
            }
            $key = switch ($label) {
                'Digesting TeX' { 'digest' }
                'Building' { 'build' }
                'Rewriting' { 'rewrite' }
                'Finalizing' { 'finalize' }
                default { $label }
            }
            $phases[$key] = [double]$token.Groups[3].Value + ($phases.Contains($key) ? [double]$phases[$key] : 0.0)
        }
        else {
            $name = $token.Groups[1].Value
            $phaseStack.Push(($name -like 'Loading*' -or $name -like 'Processing *') ? '' : $name)
        }
    }
    $fatals = Get-CountFromStatus -Line $statusLine -Pattern '(\d+) fatal errors?'
    $errors = Get-CountFromStatus -Line $statusLine -Pattern '(\d+) errors?'
    $warnings = Get-CountFromStatus -Line $statusLine -Pattern '(\d+) warnings?'
    $undefined = @(Get-ListFromStatus -Line $statusLine -Pattern '\d+ undefined macros?\[([^\]]*)\]')
    $missing = @(Get-ListFromStatus -Line $statusLine -Pattern '\d+ missing files?\[([^\]]*)\]')

    # Package routes: one row per file the engine resolved, and how.
    #   binding    a lib/LaTeXML/Package/*.ltxml file
    #   raw-local  raw TeX definitions read from the paper's own tree (--includestyles)
    #   raw        raw TeX definitions read from anywhere else on the search path
    #   missing    requested and not found (from the engine's tally)
    $packages = [System.Collections.Generic.List[object]]::new()
    foreach ($name in @($bindingLoads | Sort-Object)) {
        $packages.Add([ordered]@{ name = $name; route = 'binding' })
    }
    foreach ($rawPath in @($rawLoads | Sort-Object -Unique)) {
        $isLocal = $rawPath.StartsWith($sourceTree, [System.StringComparison]::OrdinalIgnoreCase)
        $shown = if ($isLocal) { $rawPath.Substring($sourceTree.Length).TrimStart('\', '/') } else { $rawPath }
        $packages.Add([ordered]@{
            name = [System.IO.Path]::GetFileName($rawPath)
            route = ($isLocal ? 'raw-local' : 'raw')
            path = $shown
        })
    }
    foreach ($name in @($missing | Sort-Object -Unique)) {
        $packages.Add([ordered]@{ name = $name; route = 'missing' })
    }
    $packagesRaw = @($packages | Where-Object { $_.route -like 'raw*' }).Count
    $logParseMs = [math]::Round(([datetime]::UtcNow - $logParseStarted).TotalMilliseconds, 2)

    # Undefined macros attributed to a definition site. A macro the engine reports as
    # undefined is looked up in the paper's own tree and in the vendored CTAN source of
    # every package the paper routed through. 'ctan:<pkg>/<file>' against a 'binding'
    # route is binding residue; against 'raw-local' it means raw execution did not
    # define it; 'paper:<file>' means the paper's own definition never ran; 'none'
    # means no source in reach defines it.
    $attributionStarted = [datetime]::UtcNow
    $attribution = @($undefined | ForEach-Object {
            $macro = $_
            $where = Find-DefinitionSource -Macro $macro -SourceTree $sourceTree `
                -EngineRoot $engineRoot -Packages $packages
            [ordered]@{ macro = $macro; source = $where }
        })
    $unattributed = @($attribution | Where-Object { $_.source -eq 'none' }).Count
    $attributionMs = [math]::Round(([datetime]::UtcNow - $attributionStarted).TotalMilliseconds, 2)

    $xmlBytes = 0L
    $ltxErrors = 0
    $mathElements = 0
    $danglingRefs = 0
    $internalLeaks = 0
    $errorNodes = @()
    $danglingList = @()
    $leakList = @()
    $xmlInspectStarted = [datetime]::UtcNow
    if (Test-Path -LiteralPath $xmlPath -PathType Leaf) {
        $census = Get-LaTeXAIXmlCensus -XmlPath $xmlPath
        $xmlBytes = $census.Bytes
        $ltxErrors = $census.LtxErrors
        $mathElements = $census.MathElements
        $danglingRefs = $census.DanglingRefs
        $internalLeaks = $census.InternalLeaks
        $errorNodes = @($census.ErrorNodes)
        $danglingList = @($census.DanglingList)
        $leakList = @($census.LeakList)
    }
    $xmlInspectMs = [math]::Round(([datetime]::UtcNow - $xmlInspectStarted).TotalMilliseconds, 2)

    foreach ($candidate in @($xmlPath, $logPath, $stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $stores.Add([System.IO.Path]::GetFileName($candidate))
        }
    }
    $ok = (-not $run.TimedOut) -and $run.CleanupComplete -and ($run.ExitCode -eq 0) -and ($fatals -eq 0) -and ($xmlBytes -gt 0)
    $workerMs = [math]::Round(([datetime]::UtcNow - $startedUtc).TotalMilliseconds, 2)
    $residualMs = [math]::Round($workerMs - $latexmlMs - $logParseMs - $attributionMs - $xmlInspectMs, 2)
    $counts = @{
        exitCode = if ($null -eq $run.ExitCode) { -1 } else { $run.ExitCode }
        timedOut = [int][bool]$run.TimedOut
        fatals = $fatals
        errors = $errors
        warnings = $warnings
        undefinedMacros = $undefined.Count
        undefinedUnattributed = $unattributed
        missingFiles = $missing.Count
        packagesBinding = $bindingLoads.Count
        packagesRaw = $packagesRaw
        packagesMissing = $missing.Count
        ltxErrors = $ltxErrors
        danglingRefs = $danglingRefs
        internalLeaks = $internalLeaks
        mathElements = $mathElements
        outputBytes = $xmlBytes
        latexmlMs = $latexmlMs
        logParseMs = $logParseMs
        attributionMs = $attributionMs
        xmlInspectMs = $xmlInspectMs
        workerMs = $workerMs
        residualMs = $residualMs
    }
    $taxonomyRows = @($taxonomy.GetEnumerator() | Sort-Object -Property @{ Expression = 'Value'; Descending = $true }, Name |
        ForEach-Object {
            $severity, $category, $object = $_.Name -split ':', 3
            [ordered]@{ severity = $severity; category = $category; object = $object; count = [int]$_.Value }
        })
    $details = @{
        statusLine = $statusLine
        undefinedMacros = @($undefined)
        undefinedAttribution = @($attribution)
        missingFiles = @($missing)
        packages = @($packages)
        taxonomy = @($taxonomyRows)
        errorNodes = @($errorNodes)
        danglingRefs = @($danglingList)
        internalLeaks = @($leakList)
        perl = $perl
        arguments = @($Arguments)
        conversionWorkingDirectory = $conversionCwd
        nativeOutcome = $run.Outcome
        nativeExitCode = $run.ExitCode
        nativeCleanupComplete = [bool]$run.CleanupComplete
        xmlInspectMethod = 'xml-reader'
    }
    if ($phases.Count -gt 0) { $details.phases = $phases }
    if ($null -ne $profileTotals) {
        $counts.profileCalls = $profileTotals.calls
        $details.profile = [ordered]@{
            calls = $profileTotals.calls
            maxDepth = $profileTotals.maxDepth
            frequent = @($profileLists['frequent'])
            deepest = @($profileLists['deepest'])
            inclusive = @($profileLists['inclusive'])
            exclusive = @($profileLists['exclusive'])
        }
    }
    $lsrPath = Join-Path $engineRoot 'lib-ctan/ls-R'
    if (Test-Path -LiteralPath $lsrPath -PathType Leaf) {
        $details.libCtanLsR = (Get-FileHash -LiteralPath $lsrPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    if (-not $ok -and -not $statusLine) {
        $details.stderrTail = @(($nativeStderr -split "`r?`n") | Where-Object { $_ -ne '' } | Select-Object -Last 20)
    }
    return [pscustomobject]@{Status=($ok ? 'ok' : 'failed');Counts=$counts;Details=$details;Stores=$stores.ToArray()}
}
