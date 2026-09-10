#requires -Version 7.5
<# Compare the two Markdown traversals on a hash-pinned input manifest.
   Preparation runs once per input. Each strategy gets its own Perl process,
   one untimed warmup and repeated runs over the same parsed DOM. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $Manifest,
    [Parameter(Mandatory)][string] $OutputDirectory,
    [ValidateRange(3, 99)][int] $Repetitions = 9,
    [string] $PerlRoot = '',
    [nullable[int]] $TimeoutSeconds = $null
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'latexai-common.ps1')
$runtime = Resolve-LaTeXAIRuntime -PerlRoot $PerlRoot -RequirePerl
Set-LaTeXAIRuntimeEnvironment -Runtime $runtime
$repo = $runtime.CheckoutRoot
$perl = $runtime.PerlPath
$manifestPath = (Resolve-Path -LiteralPath $Manifest).Path
$source = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json -DateKind String
if ($source.schema -ne 'latexai/markdown-projection-inputs/0.1') { throw 'Unsupported input manifest' }
$outRoot = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $outRoot) { throw "Choose a new output directory; refusing to overwrite $outRoot" }
[IO.Directory]::CreateDirectory($outRoot) | Out-Null
$utf8 = [Text.UTF8Encoding]::new($false)
$mdTimeout = Get-LaTeXAINativeTimeoutSeconds -Family Markdown -Override $TimeoutSeconds
$mdCleanup = [int]$runtime.Policy.Markdown.CleanupTimeoutSeconds
$mdSlice = [int]$runtime.Policy.Markdown.WaitSliceMilliseconds
function Invoke-Perl {
    param([string[]] $Arguments, [string] $Log)
    $stdoutPath = [IO.Path]::ChangeExtension($Log, '.stdout.txt')
    if ($stdoutPath -eq $Log) { $stdoutPath = "$Log.stdout.txt" }
    $stderrPath = [IO.Path]::ChangeExtension($Log, '.stderr.txt')
    if ($stderrPath -eq $Log) { $stderrPath = "$Log.stderr.txt" }
    $run = Invoke-LaTeXAINative -FilePath $perl -Arguments $Arguments -WorkingDirectory $repo `
        -TimeoutSeconds $mdTimeout -CleanupTimeoutSeconds $mdCleanup `
        -WaitSliceMilliseconds $mdSlice -StdOutPath $stdoutPath -StdErrPath $stderrPath `
        -SamplePeakWorkingSet
    if ($run.TimedOut -or $run.Outcome -eq 'failed-to-launch' -or $run.ExitCode -ne 0) {
        throw "Perl $($run.Outcome) exit $($run.ExitCode):`n$($run.StdOut)`n$($run.StdErr)"
    }
    return [ordered]@{
        process_ms = $run.DurationMs
        sampled_peak_working_set_bytes = $run.PeakWorkingSetBytes
        stdout_path = $stdoutPath
        stderr_path = $stderrPath
        timeout_seconds = $run.TimeoutSecondsEffective
    }
}
$rows = [Collections.Generic.List[object]]::new()
$index = 0
foreach ($item in $source.inputs) {
    foreach ($pair in @(@{Path = $item.xml; Hash = $item.xmlSha256 }, @{Path = $item.receipt; Hash = $item.receiptSha256 })) {
        if ((Get-FileHash -LiteralPath $pair.Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pair.Hash) {
            throw "Input drift: $($pair.Path)"
        }
    }
    $dir = Join-Path $outRoot $item.slug
    [IO.Directory]::CreateDirectory($dir) | Out-Null
    $paths = @($item.arguments | Where-Object { $_ -like '--path=*' } | ForEach-Object { $_.Substring(7) })
    if ($paths.Count -eq 0) { throw "No source path in receipt for $($item.slug)" }
    $assetRoot = $paths[0]
    $prepared = Join-Path $dir 'prepared.xml'
    $prepReport = Join-Path $dir 'preparation.json'
    $args = @('bin/latexai-markdown', '--prepare-only', '--output', $prepared, '--report', $prepReport, '--asset-root', $assetRoot)
    foreach ($path in $paths) { $args += @('--path', $path) }
    $args += $item.xml
    $prepProcess = Invoke-Perl -Arguments $args -Log (Join-Path $dir 'preparation.log')
    $strategies = if ($index++ % 2 -eq 0) { @('deferred', 'indexed') } else { @('indexed', 'deferred') }
    $results = @{}
    foreach ($strategy in $strategies) {
        $md = Join-Path $dir "$strategy.md"
        $json = Join-Path $dir "$strategy.json"
        $processStats = Invoke-Perl -Arguments @('tools/dev/markdown-benchmark.pl', $prepared, $strategy, [string]$Repetitions, $md, $json, $assetRoot) -Log (Join-Path $dir "$strategy.log")
        $result = Get-Content -LiteralPath $json -Raw | ConvertFrom-Json -DateKind String
        $result | Add-Member -NotePropertyName process -NotePropertyValue $processStats
        [IO.File]::WriteAllText($json, ($result | ConvertTo-Json -Depth 30) + "`n", $utf8)
        $results[$strategy] = $result
    }
    if ($results.deferred.output_sha256 -ne $results.indexed.output_sha256) { throw "Strategy output mismatch: $($item.slug)" }
    $left = @($results.deferred.projection.issues | ForEach-Object { $_ | ConvertTo-Json -Compress } | Sort-Object) -join "`n"
    $right = @($results.indexed.projection.issues | ForEach-Object { $_ | ConvertTo-Json -Compress } | Sort-Object) -join "`n"
    if ($left -ne $right) { throw "Strategy diagnostic mismatch: $($item.slug)" }
    $row = [ordered]@{
        slug = $item.slug; input_sha256 = $item.xmlSha256
        prepared_sha256 = (Get-FileHash -LiteralPath $prepared -Algorithm SHA256).Hash.ToLowerInvariant()
        preparation = (Get-Content -LiteralPath $prepReport -Raw | ConvertFrom-Json)
        preparation_process = $prepProcess; strategy_order = $strategies
        deferred_ms = $results.deferred.medians_ms.call; indexed_ms = $results.indexed.medians_ms.call
        deferred_visits = $results.deferred.projection.counters.emit_visits
        indexed_visits = $results.indexed.projection.counters.emit_visits + $results.indexed.projection.counters.index_visits
        label_visits = $results.deferred.projection.counters.label_visits
        deferred_peak_bytes = $results.deferred.process.sampled_peak_working_set_bytes
        indexed_peak_bytes = $results.indexed.process.sampled_peak_working_set_bytes
        markdown_sha256 = $results.deferred.output_sha256; identical = $true
        selected_math = $results.deferred.projection.math.Count
        bibliography_entries = $results.deferred.projection.bibliography_entries
        projection_notices = $results.deferred.projection.issues.Count
        input_counts = $item.counts
    }
    $rows.Add($row)
    Write-Host ('{0}: deferred={1:N2} ms indexed={2:N2} ms; identical; math={3} bibliography={4}' -f $row.slug, $row.deferred_ms, $row.indexed_ms, $row.selected_math, $row.bibliography_entries)
}
$code = @(Get-Item -LiteralPath (Join-Path $repo 'lib/LaTeXAI/Post.pm'), (Join-Path $repo 'lib/LaTeXAI/Post/Markdown.pm'), (Join-Path $repo 'bin/latexai-markdown'), (Join-Path $repo 'tools/dev/markdown-benchmark.pl'), $PSCommandPath | ForEach-Object {
        [ordered]@{path = $_.FullName; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
$report = [ordered]@{
    schema = 'latexai/markdown-traversal-comparison/0.1'; created_utc = [datetime]::UtcNow.ToString('o')
    manifest = $manifestPath; manifest_sha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    checkout_commit = (& git -C $repo rev-parse HEAD); code = $code; repetitions = $Repetitions
    method = 'Sequential isolated process per input/strategy; alternating strategy order across papers; one untimed warmup, then repeated projections of one parsed DOM. Native waits use scripts/latexai-common.ps1 Invoke-LaTeXAINative. Preparation, parse, projection phases and process peak working set (sampled on the wait slice while alive; metric still sampled_peak_working_set_bytes) reported separately. Stdout and stderr are retained as sibling .stdout.txt/.stderr.txt files, not concatenated into the only log.'
    limits = 'Both implementations buffer Markdown fragments. This compares traversal organization, not streaming-memory behavior or LaTeXML HTML speed. Sampled peak working set includes runtime, parser and warmup, may miss the final 20 ms, and is not incremental projector allocation. Input diagnostics remain independent.'
    inputs = $rows.ToArray()
}
[IO.File]::WriteAllText((Join-Path $outRoot 'comparison.json'), ($report | ConvertTo-Json -Depth 30) + "`n", $utf8)
Write-Host "Comparison saved: $outRoot"
