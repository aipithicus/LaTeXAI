#requires -Version 7.0
<# Compare the two Markdown traversals on a hash-pinned input manifest.
   Preparation runs once per input. Each strategy gets its own Perl process,
   one untimed warmup and repeated runs over the same parsed DOM. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $Manifest,
    [Parameter(Mandatory)][string] $OutputDirectory,
    [ValidateRange(3, 99)][int] $Repetitions = 9
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
if (-not $env:PERL_ROOT) { throw 'Use the repository pwsh_exec profile: PERL_ROOT is required.' }
$perl = Join-Path $env:PERL_ROOT 'perl/bin/perl.exe'
$manifestPath = (Resolve-Path -LiteralPath $Manifest).Path
$source = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($source.schema -ne 'latexai/markdown-projection-inputs/0.1') { throw 'Unsupported input manifest' }
$outRoot = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $outRoot) { throw "Choose a new output directory; refusing to overwrite $outRoot" }
[IO.Directory]::CreateDirectory($outRoot) | Out-Null
$utf8 = [Text.UTF8Encoding]::new($false)
function Invoke-Perl {
    param([string[]] $Arguments, [string] $Log)
    $psi = [Diagnostics.ProcessStartInfo]::new($perl)
    $psi.WorkingDirectory = $repo
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    foreach ($arg in $Arguments) { $psi.ArgumentList.Add($arg) }
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $process = [Diagnostics.Process]::Start($psi)
    try {
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $peak = $null
        do {
            $process.Refresh()
            $observed = $process.PeakWorkingSet64
            if ($observed -gt $peak) { $peak = $observed }
        } until ($process.WaitForExit(20))
        $timer.Stop()
        $text = $stdout.GetAwaiter().GetResult() + $stderr.GetAwaiter().GetResult()
        [IO.File]::WriteAllText($Log, $text, $utf8)
        if ($process.ExitCode -ne 0) { throw "Perl exit $($process.ExitCode):`n$text" }
        return [ordered]@{ process_ms = $timer.Elapsed.TotalMilliseconds; sampled_peak_working_set_bytes = $peak }
    }
    finally { $process.Dispose() }
}
$rows = [Collections.Generic.List[object]]::new()
$index = 0
foreach ($item in $source.inputs) {
    foreach ($pair in @(@{Path=$item.xml;Hash=$item.xmlSha256},@{Path=$item.receipt;Hash=$item.receiptSha256})) {
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
    $args = @('bin/latexai-markdown','--prepare-only','--output',$prepared,'--report',$prepReport,'--asset-root',$assetRoot)
    foreach ($path in $paths) { $args += @('--path',$path) }
    $args += $item.xml
    $prepProcess = Invoke-Perl -Arguments $args -Log (Join-Path $dir 'preparation.log')
    $strategies = if ($index++ % 2 -eq 0) { @('deferred','indexed') } else { @('indexed','deferred') }
    $results = @{}
    foreach ($strategy in $strategies) {
        $md = Join-Path $dir "$strategy.md"
        $json = Join-Path $dir "$strategy.json"
        $processStats = Invoke-Perl -Arguments @('tools/dev/markdown-benchmark.pl',$prepared,$strategy,[string]$Repetitions,$md,$json,$assetRoot) -Log (Join-Path $dir "$strategy.log")
        $result = Get-Content -LiteralPath $json -Raw | ConvertFrom-Json
        $result | Add-Member -NotePropertyName process -NotePropertyValue $processStats
        [IO.File]::WriteAllText($json,($result | ConvertTo-Json -Depth 30)+"`n",$utf8)
        $results[$strategy] = $result
    }
    if ($results.deferred.output_sha256 -ne $results.indexed.output_sha256) { throw "Strategy output mismatch: $($item.slug)" }
    $left = @($results.deferred.projection.issues | ForEach-Object {$_ | ConvertTo-Json -Compress} | Sort-Object) -join "`n"
    $right = @($results.indexed.projection.issues | ForEach-Object {$_ | ConvertTo-Json -Compress} | Sort-Object) -join "`n"
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
    Write-Host ('{0}: deferred={1:N2} ms indexed={2:N2} ms; identical; math={3} bibliography={4}' -f $row.slug,$row.deferred_ms,$row.indexed_ms,$row.selected_math,$row.bibliography_entries)
}
$code = @(Get-Item -LiteralPath (Join-Path $repo 'lib/LaTeXAI/Post.pm'),(Join-Path $repo 'lib/LaTeXAI/Post/Markdown.pm'),(Join-Path $repo 'bin/latexai-markdown'),(Join-Path $repo 'tools/dev/markdown-benchmark.pl'),$PSCommandPath | ForEach-Object {
    [ordered]@{path=$_.FullName;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
})
$report = [ordered]@{
    schema='latexai/markdown-traversal-comparison/0.1'; created_utc=[datetime]::UtcNow.ToString('o')
    manifest=$manifestPath; manifest_sha256=(Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    checkout_commit=(& git -C $repo rev-parse HEAD); code=$code; repetitions=$Repetitions
    method='Sequential isolated process per input/strategy; alternating strategy order across papers; one untimed warmup, then repeated projections of one parsed DOM. Preparation, parse, projection phases and process peak working set (sampled every 20 ms while alive) reported separately.'
    limits='Both implementations buffer Markdown fragments. This compares traversal organization, not streaming-memory behavior or LaTeXML HTML speed. Sampled peak working set includes runtime, parser and warmup, may miss the final 20 ms, and is not incremental projector allocation. Input diagnostics remain independent.'
    inputs=$rows.ToArray()
}
[IO.File]::WriteAllText((Join-Path $outRoot 'comparison.json'),($report | ConvertTo-Json -Depth 30)+"`n",$utf8)
Write-Host "Comparison saved: $outRoot"
