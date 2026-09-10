#requires -Version 7.5
<#
  scripts/gauntlet-worker.ps1 — codex-scientiae inventory worker for
  the LaTeXAI engine.

  One deposit per invocation. codex-scientiae's inventory planner hands over
  everything the inventory row resolved (Article, SourceTree, Entrypoint,
  TreeSha256) plus the job container (OutDirectory, not yet created) and this
  repository (EngineRoot). The worker runs bin/latexml over the entrypoint,
  keeps every byte it writes inside OutDirectory (log, stdout, stderr, the
  ltx XML), and leaves receipt.json at the top of OutDirectory with schema
  codex-scientiae/inventory-receipt/0.1. It exits non-zero when the
  conversion failed. It opens neither article.json nor the inventory.

  Contract: the inventory worker contract under CDXSCI_ROOT
  src/batch-adapters/README.md. Launcher: scripts/gauntlet-run.ps1.

  Native stderr is routed to a file, never into the PowerShell error stream:
  the child bootstrap treats any error record as failure, and LaTeXML writes
  its progress to stderr.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Article,
    [Parameter(Mandatory)] [string] $OutDirectory,
    [Parameter(Mandatory)] [string] $EngineRoot,
    [Parameter(Mandatory)] [string] $SourceTree,
    [Parameter(Mandatory)] [string] $Entrypoint,
    [Parameter(Mandatory)] [string] $TreeSha256,
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
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'latexai-common.ps1')
$startedUtc = [datetime]::UtcNow
$utf8 = [System.Text.UTF8Encoding]::new($false)
$engineName = 'latexai'
$slug = [System.IO.Path]::GetFileName($Article.TrimEnd('\', '/'))
$receiptPath = Join-Path $OutDirectory 'receipt.json'

function Write-Receipt {
    param(
        [Parameter(Mandatory)] [string] $Status,
        [hashtable] $Counts = @{},
        [hashtable] $Details = @{},
        [string[]] $Stores = @()
    )
    $endedUtc = [datetime]::UtcNow
    $receipt = [ordered]@{
        schema = 'codex-scientiae/inventory-receipt/0.1'
        engine = $engineName
        engineVersion = $script:EngineVersion
        engineCommit = $script:EngineCommit
        article = [ordered]@{
            slug = $slug
            treeSha256 = $TreeSha256
            directory = $Article
        }
        entrypoint = $Entrypoint
        status = $Status
        startedUtc = $startedUtc.ToString('o')
        endedUtc = $endedUtc.ToString('o')
        durationMs = [math]::Round(($endedUtc - $startedUtc).TotalMilliseconds, 2)
        stores = @($Stores)
        counts = [ordered]@{}
        details = [ordered]@{}
    }
    foreach ($key in ($Counts.Keys | Sort-Object)) { $receipt.counts[$key] = $Counts[$key] }
    foreach ($key in ($Details.Keys | Sort-Object)) { $receipt.details[$key] = $Details[$key] }
    [System.IO.File]::WriteAllText($receiptPath, (($receipt | ConvertTo-Json -Depth 8) + "`n"), $utf8)
}

function Resolve-Perl {
    param([string] $Candidate)
    if (-not [string]::IsNullOrWhiteSpace($Candidate)) {
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { throw "PerlPath not found: '$Candidate'" }
        return (Resolve-Path -LiteralPath $Candidate).Path
    }
    $root = [System.Environment]::GetEnvironmentVariable('PERL_ROOT')
    if ([string]::IsNullOrWhiteSpace($root)) {
        throw 'no perl: the launcher must pass -PerlPath or set PERL_ROOT before starting the worker'
    }
    $fromRoot = Join-Path $root 'perl/bin/perl.exe'
    if (-not (Test-Path -LiteralPath $fromRoot -PathType Leaf)) {
        throw "PERL_ROOT does not contain Strawberry perl: '$fromRoot'"
    }
    return (Resolve-Path -LiteralPath $fromRoot).Path
}

function Invoke-Native {
    param(
        [Parameter(Mandatory)] [string] $FilePath,
        [string[]] $Arguments = @(),
        [string] $WorkingDirectory = '',
        [int] $TimeoutSeconds = 0
    )
    $run = Invoke-LaTeXAINative -FilePath $FilePath -Arguments $Arguments `
        -WorkingDirectory $WorkingDirectory -TimeoutSeconds $TimeoutSeconds
    return [pscustomobject]@{
        ExitCode = $run.ExitCode
        StdOut = [string]$run.StdOut
        StdErr = [string]$run.StdErr
        TimedOut = [bool]$run.TimedOut
        Outcome = [string]$run.Outcome
        DurationMs = $run.DurationMs
        CleanupComplete = [bool]$run.CleanupComplete
    }
}

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

$stores = [System.Collections.Generic.List[string]]::new()
try {
    [void][System.IO.Directory]::CreateDirectory($OutDirectory)
    $jobTemp = [System.Environment]::GetEnvironmentVariable('CDXSCI_TEMP')
    if (-not [string]::IsNullOrWhiteSpace($jobTemp)) { [void][System.IO.Directory]::CreateDirectory($jobTemp) }

    $engineRoot = (Resolve-Path -LiteralPath $EngineRoot).Path
    $sourceTree = (Resolve-Path -LiteralPath $SourceTree).Path
    $entryFile = Join-Path $sourceTree $Entrypoint
    if (-not (Test-Path -LiteralPath $entryFile -PathType Leaf)) {
        throw "entrypoint not found in source tree: '$entryFile'"
    }
    $libDirectory = Join-Path $engineRoot 'lib'
    $latexml = Join-Path $engineRoot 'bin/latexml'
    foreach ($required in @($libDirectory, $latexml, (Join-Path $libDirectory 'LaTeXML/Version.pm'))) {
        if (-not (Test-Path -LiteralPath $required)) {
            throw "engine incomplete: '$required' (run lgen after a fresh clone)"
        }
    }
    $perl = Resolve-Perl -Candidate $PerlPath
    if ([string]::IsNullOrWhiteSpace([System.Environment]::GetEnvironmentVariable('PERL_ROOT'))) {
        $perlFile = Get-Item -LiteralPath $perl
        [System.Environment]::SetEnvironmentVariable('PERL_ROOT', $perlFile.Directory.Parent.Parent.FullName)
    }
    if ($Kpsewhich) {
        $kpseCmd = Join-Path $engineRoot 'scripts/kpsewhich.cmd'
        if (Test-Path -LiteralPath $kpseCmd -PathType Leaf) {
            $env:LATEXML_KPSEWHICH = (Resolve-Path -LiteralPath $kpseCmd).Path
            $env:LATEXML_KPSEWHICH_CACHE_ONLY = '1'
        }
    }
    else {
        Remove-Item -LiteralPath Env:LATEXML_KPSEWHICH -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath Env:LATEXML_KPSEWHICH_CACHE_ONLY -ErrorAction SilentlyContinue
    }

    $nativeTimeout = $TimeoutSeconds
    if ($nativeTimeout -lt 0) { $nativeTimeout = Get-LaTeXAINativeTimeoutSeconds -Family Gauntlet }

    if ([string]::IsNullOrWhiteSpace($EngineVersion)) {
        $probe = Invoke-Native -FilePath $perl -WorkingDirectory $engineRoot -TimeoutSeconds 30 `
            -Arguments @('-I', $libDirectory, '-MLaTeXML', '-e', 'print $LaTeXML::VERSION')
        $script:EngineVersion = if ($probe.ExitCode -eq 0) { $probe.StdOut.Trim() } else { 'unknown' }
    }
    if ([string]::IsNullOrWhiteSpace($EngineCommit)) {
        $probe = Invoke-Native -FilePath 'git' -WorkingDirectory $engineRoot -TimeoutSeconds 30 `
            -Arguments @('rev-parse', '--short', 'HEAD')
        $script:EngineCommit = if ($probe.ExitCode -eq 0) { $probe.StdOut.Trim() } else { 'unknown' }
    }

    $logPath = Join-Path $OutDirectory 'latexml.log'
    $xmlPath = Join-Path $OutDirectory "$slug.xml"
    $stdoutPath = Join-Path $OutDirectory 'latexml.stdout.txt'
    $stderrPath = Join-Path $OutDirectory 'latexml.stderr.txt'

    $arguments = [System.Collections.Generic.List[string]]::new()
    $arguments.Add('-I'); $arguments.Add($libDirectory)
    $arguments.Add($latexml)
    if ($IncludeStyles) { $arguments.Add('--includestyles') }
    $arguments.Add("--path=$sourceTree")
    foreach ($entry in @($SearchPath)) {
        if ([string]::IsNullOrWhiteSpace($entry)) { continue }
        $resolved = if ([System.IO.Path]::IsPathFullyQualified($entry)) { $entry } else { Join-Path $engineRoot $entry }
        $arguments.Add("--path=$resolved")
    }
    foreach ($module in @($Preload)) {
        if (-not [string]::IsNullOrWhiteSpace($module)) { $arguments.Add("--preload=$module") }
    }
    foreach ($extra in @($LatexmlArgument)) {
        if (-not [string]::IsNullOrWhiteSpace($extra)) { $arguments.Add($extra) }
    }
    $arguments.Add("--log=$logPath")
    $arguments.Add("--destination=$xmlPath")
    $conversionCwd = $sourceTree
    $sourceArgument = $Entrypoint
    if ($ConversionWorkingDirectory -eq 'output') {
        $conversionCwd = $OutDirectory
        $sourceArgument = $entryFile
    }
    $arguments.Add($sourceArgument)

    $run = Invoke-Native -FilePath $perl -Arguments $arguments.ToArray() `
        -WorkingDirectory $conversionCwd -TimeoutSeconds $nativeTimeout
    $latexmlMs = [double]$run.DurationMs
    [System.IO.File]::WriteAllText($stdoutPath, $run.StdOut, $utf8)
    [System.IO.File]::WriteAllText($stderrPath, $run.StdErr, $utf8)
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
    $phaseTokens = [regex]::Matches($run.StdErr,
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
        $xmlBytes = [System.IO.FileInfo]::new($xmlPath).Length
        $xmlText = [System.IO.File]::ReadAllText($xmlPath)
        # The CLI emits the ltx namespace as the default (no prefix); goldens use the prefix.
        $ltxErrors = [regex]::Matches($xmlText, '<(?:ltx:)?ERROR\b').Count
        $mathElements = [regex]::Matches($xmlText, '<(?:ltx:)?Math\b').Count
        $errorNodes = @([regex]::Matches($xmlText, '<(?:ltx:)?ERROR[^>]*>([^<]{1,80})') |
            ForEach-Object { $_.Groups[1].Value.Trim() } | Sort-Object -Unique | Select-Object -First 40)
        # The golden lint's two checks, on a real document: a reference whose target label
        # is on no element, and an engine-internal \lx@ control sequence leaked into the IR.
        $labelSet = [System.Collections.Generic.HashSet[string]]::new()
        foreach ($m in [regex]::Matches($xmlText, ' labels="([^"]*)"')) {
            foreach ($token in ($m.Groups[1].Value -split '\s+')) { if ($token) { [void]$labelSet.Add($token) } }
        }
        $dangling = [System.Collections.Generic.List[string]]::new()
        foreach ($m in [regex]::Matches($xmlText, ' labelref="([^"]*)"')) {
            foreach ($token in ($m.Groups[1].Value -split '\s+')) {
                if ($token -and -not $labelSet.Contains($token)) { $dangling.Add($token) }
            }
        }
        $danglingRefs = $dangling.Count
        $danglingList = @($dangling | Sort-Object -Unique | Select-Object -First 40)
        $leaks = [regex]::Matches($xmlText, '\\lx@[A-Za-z@]*')
        $internalLeaks = $leaks.Count
        $leakList = @($leaks | ForEach-Object { $_.Value } | Sort-Object -Unique | Select-Object -First 40)
        $xmlText = $null
    }
    $xmlInspectMs = [math]::Round(([datetime]::UtcNow - $xmlInspectStarted).TotalMilliseconds, 2)

    foreach ($candidate in @($xmlPath, $logPath, $stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $stores.Add([System.IO.Path]::GetFileName($candidate))
        }
    }
    $stores.Add('receipt.json')

    $ok = (-not $run.TimedOut) -and ($run.ExitCode -eq 0) -and ($fatals -eq 0) -and ($xmlBytes -gt 0)
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
        arguments = @($arguments.ToArray())
        conversionWorkingDirectory = $conversionCwd
        nativeOutcome = $run.Outcome
        nativeCleanupComplete = [bool]$run.CleanupComplete
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
        $details.stderrTail = @(($run.StdErr -split "`r?`n") | Where-Object { $_ -ne '' } | Select-Object -Last 20)
    }
    Write-Receipt -Status ($ok ? 'ok' : 'failed') -Counts $counts -Details $details -Stores $stores.ToArray()
    if (-not $ok) {
        # The executor's child bootstrap observes error records, not exit codes:
        # the entrypoint is invoked with & inside its pipeline. Throw to fail the job.
        throw "conversion failed for ${slug}: exit=$($run.ExitCode) fatals=$fatals bytes=$xmlBytes $statusLine"
    }
}
catch {
    $message = $_.Exception.Message
    if ($message -notlike 'conversion failed for *') {
        try {
            if (-not $stores.Contains('receipt.json')) { $stores.Add('receipt.json') }
            Write-Receipt -Status 'failed' -Counts @{ exitCode = -1 } -Details @{ workerError = $message } `
                -Stores $stores.ToArray()
        }
        catch { }
    }
    throw "gauntlet-worker: $message"
}
