#requires -Version 7.5
# Log-only controls: no conversion, external corpus, or XML inspection required.
[CmdletBinding()]
param([string] $RunDirectory = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $root 'scripts/gauntlet-measure.ps1')
if (-not $RunDirectory) {
    $RunDirectory = Join-Path $root ('temp/t/gauntlet-measure/' + [guid]::NewGuid().ToString('N'))
}
[void][IO.Directory]::CreateDirectory($RunDirectory)
$checks = 0
function Assert-Phase([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw $Message }
    $script:checks++
}
function Measure-Log([string] $Text) {
    [IO.File]::WriteAllText((Join-Path $RunDirectory 'latexml.stderr.txt'), $Text, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $RunDirectory 'latexml.log'), $Text, [Text.UTF8Encoding]::new($false))
    $run = @{DurationMs=0;StdErr='';TimedOut=$false;CleanupComplete=$true;ExitCode=0;Outcome='exited'}
    $result = Measure-LaTeXAICondition -Article 'paper' -OutDirectory $RunDirectory -EngineRoot $RunDirectory `
        -SourceTree ([IO.Path]::GetFullPath($RunDirectory)) -Perl 'unused' -Arguments @() -ConversionCwd $RunDirectory `
        -Run $run -StartedUtc ([datetime]::UtcNow)
    return $result.Details
}

# Reduced from 1602.04426v2: a Note inside xcolor's timed load must not consume
# the enclosing content/digest close. Parenthesized paths and same-line closes
# are valid; timings are inclusive and must not be added to their parent.
$log = @'
(Digesting TeX paper...
(Loading engine (local)/TeX.pool.ltxml... 0.81 sec)
(Processing content paper.tex...
(Processing definitions journal.cls...
(Loading xcolor.sty.ltxml...
(Loading generated xcolor name data x11nam.def)
 0.37 sec)
 2.68 sec)
(Processing content paper.bbl... 2.61 sec) 18.19 sec) 19.03 sec)
(Building...
(Loading compiled schema LaTeXML.model... 0.03 sec)
 13.84 sec)
(Rewriting... 0.50 sec)
(Math Parsing 628 formulae ...... 23.71 sec)
(Finalizing... 2.45 sec)
'@
$details = Measure-Log $log
$expected = @{digest=19.03;build=13.84;rewrite=0.50;mathParse=23.71;formulae=628;finalize=2.45}
foreach ($key in $expected.Keys) {
    Assert-Phase ($details.phases[$key] -eq $expected[$key]) "Incorrect inclusive phase: $key"
}
$crlf = Measure-Log ($log.Replace("`n", "`r`n"))
Assert-Phase ($crlf.phases.digest -eq 19.03) 'CRLF progress was not parsed'
$listings = Measure-Log ($log.Replace('Loading generated xcolor name data x11nam.def', 'Loading generated listings language data lstlang1.sty'))
Assert-Phase ($listings.phases.digest -eq 19.03) 'Untimed listings load shifted the phase stack'
$repeated = Measure-Log "(Digesting TeX first... 1.25 sec)`n(Digesting TeX second... 2.50 sec)"
Assert-Phase ($repeated.phases.digest -eq 3.75) 'Repeated completed digests were not summed'
$truncated = Measure-Log "(Digesting TeX paper...`n(Loading module... 0.25 sec)"
Assert-Phase (-not $truncated.ContainsKey('phases')) 'Incomplete digest was assigned a child timing'
$noMath = Measure-Log "(Digesting TeX paper... 1.00 sec)`n(Building... 0.10 sec)`n(Rewriting... 0.00 sec)`n(Finalizing... 0.01 sec)"
Assert-Phase (-not $noMath.phases.Contains('mathParse') -and -not $noMath.phases.Contains('formulae')) 'Absent math parsing was invented'
$note = Measure-Log "Info:note:example (Digesting TeX example...`n(Loading generated xcolor name data x11nam.def)"
Assert-Phase (-not $note.ContainsKey('phases')) 'Ordinary diagnostic was treated as a completed phase'

# Mouth::initialize reports the @ catcode before the source path. This note
# must not become part of a raw package path or hide a paper-local route.
$enginePath = 'D:/engine (frozen)/lib-ctan/example/tex/xy.tex'
$localRoot = ([IO.Path]::GetFullPath($RunDirectory)).Replace('\', '/').TrimEnd('/')
$localPath = $localRoot + '/local package (v1).sty'
$siblingPath = $localRoot + '-sibling/foreign.sty'
$literalPath = 'D:/engine (frozen)/lib-ctan/w/@ other/example.sty'
$routes = Measure-Log @"
(Processing definitions $enginePath... 0.01 sec)
(Processing definitions w/@ other $enginePath... 0.01 sec)
(Processing definitions w/@ other $localPath... 0.01 sec)
(Processing definitions $literalPath... 0.01 sec)
(Processing definitions $siblingPath... 0.01 sec)
"@
Assert-Phase ($routes.packages.Count -eq 4) 'Annotated and ordinary loads of the same path were not deduplicated'
$engineRoute = @($routes.packages | Where-Object name -eq 'xy.tex')
Assert-Phase ($engineRoute.Count -eq 1 -and $engineRoute[0].path -ceq $enginePath -and $engineRoute[0].route -eq 'raw') 'Definitions annotation leaked into an engine package path'
$localRoute = @($routes.packages | Where-Object name -eq 'local package (v1).sty')
Assert-Phase ($localRoute.Count -eq 1 -and $localRoute[0].route -eq 'raw-local' -and $localRoute[0].path -ceq 'local package (v1).sty') 'Annotated paper package lost its local route'
Assert-Phase (@($routes.packages | Where-Object { $_.path -ceq $literalPath }).Count -eq 1) 'Annotation-like text inside a source path was changed'
$siblingRoute = @($routes.packages | Where-Object name -eq 'foreign.sty')
Assert-Phase ($siblingRoute.Count -eq 1 -and $siblingRoute[0].route -eq 'raw' -and $siblingRoute[0].path -ceq $siblingPath) 'A sibling of the paper directory was classified as local'
[ordered]@{passed=$checks;runDirectory=$RunDirectory} | ConvertTo-Json
