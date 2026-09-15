#requires -Version 7.5
# Conversion and measurements shared by acquisition and paper experiments.
. (Join-Path $PSScriptRoot 'gauntlet-measure.ps1')
function Invoke-LaTeXAICondition {
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
    [ValidateSet('source', 'output')] [string] $ConversionWorkingDirectory = 'source',
    [string] $ConditionId = 'conversion',
    [switch] $SamplePeakWorkingSet
)

$startedUtc=[datetime]::UtcNow
$nativeResult=$null
$slug=[IO.Path]::GetFileName($Article.TrimEnd('\','/'))
$script:EngineVersion=$EngineVersion
$script:EngineCommit=$EngineCommit
function Complete-LaTeXAICondition {
    param([string]$Status,[hashtable]$Counts=@{},[hashtable]$Details=@{},[string[]]$Stores=@())
    $artifacts=@(foreach($name in @(@($Stores)+@("$slug.xml",'latexml.log','latexml.stdout.txt','latexml.stderr.txt')|Sort-Object -Unique)){
        $file=Join-Path $OutDirectory $name
        if(Test-Path -LiteralPath $file -PathType Leaf){@{path="conditions/$ConditionId/$name";sha256=(Get-InventoryFileReference $file).sha256;bytes=(Get-Item -LiteralPath $file).Length}}
    })
    $outputs=@{}
    if(Test-Path -LiteralPath (Join-Path $OutDirectory "$slug.xml") -PathType Leaf){$outputs.xml="conditions/$ConditionId/$slug.xml"}
    $Details.sourceTree=$SourceTree
    $memory=@{method='unavailable';bytes=$null}
    if($null -ne $nativeResult -and $nativeResult.SampledPeakWorkingSet){$memory=@{method='sampled-process-PeakWorkingSet64';bytes=$nativeResult.PeakWorkingSetBytes}}
    $condition=[ordered]@{
        id=$ConditionId;status=$Status;engine=@{root=$EngineRoot;version=$script:EngineVersion;commit=$script:EngineCommit}
        execution=@{outcome=($Details.ContainsKey('nativeOutcome') ? $Details.nativeOutcome : 'not-started')
            exitCode=($Details.ContainsKey('nativeExitCode') ? $Details.nativeExitCode : $null)
            timedOut=($Counts.ContainsKey('timedOut') ? [bool]$Counts.timedOut : $null)
            cleanupComplete=($Details.ContainsKey('nativeCleanupComplete') ? $Details.nativeCleanupComplete : $null)}
        outputs=$outputs;counts=$Counts;details=$Details
        durationMs=([datetime]::UtcNow-$startedUtc).TotalMilliseconds;memory=$memory
    }
    return [pscustomobject]@{Condition=$condition;Artifacts=$artifacts}
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
        [int] $TimeoutSeconds = 0,
        [string] $StdOutPath = '',
        [string] $StdErrPath = '',
        [switch] $SamplePeakWorkingSet
    )
    $run = Invoke-LaTeXAINative -FilePath $FilePath -Arguments $Arguments `
        -WorkingDirectory $WorkingDirectory -TimeoutSeconds $TimeoutSeconds `
        -StdOutPath $StdOutPath -StdErrPath $StdErrPath -SamplePeakWorkingSet:$SamplePeakWorkingSet
    return [pscustomobject]@{
        ExitCode = $run.ExitCode
        StdOut = [string]$run.StdOut
        StdErr = [string]$run.StdErr
        TimedOut = [bool]$run.TimedOut
        Outcome = [string]$run.Outcome
        DurationMs = $run.DurationMs
        CleanupComplete = [bool]$run.CleanupComplete
        PeakWorkingSetBytes = $run.PeakWorkingSetBytes
        SampledPeakWorkingSet = $run.SampledPeakWorkingSet
    }
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
        $git = (Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
        $probe = Invoke-Native -FilePath $git -WorkingDirectory $engineRoot -TimeoutSeconds 30 `
            -Arguments @('rev-parse', '--short', 'HEAD')
        if ($probe.ExitCode -ne 0 -or -not $probe.CleanupComplete) { throw "git identity probe failed: $($probe.StdErr)" }
        $script:EngineCommit = $probe.StdOut.Trim()
        $dirty = Invoke-Native -FilePath $git -WorkingDirectory $engineRoot -TimeoutSeconds 30 `
            -Arguments @('status', '--porcelain')
        if ($dirty.ExitCode -ne 0 -or -not $dirty.CleanupComplete) { throw "git status probe failed: $($dirty.StdErr)" }
        if ($dirty.StdOut.Trim()) { $script:EngineCommit += '+dirty' }
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
        -WorkingDirectory $conversionCwd -TimeoutSeconds $nativeTimeout `
        -StdOutPath $stdoutPath -StdErrPath $stderrPath -SamplePeakWorkingSet:$SamplePeakWorkingSet
    $nativeResult = $run
    $latexmlMs = [double]$run.DurationMs
    $measureArgs=@{Article=$Article;OutDirectory=$OutDirectory;EngineRoot=$engineRoot;SourceTree=$sourceTree;Perl=$perl;Arguments=$arguments.ToArray();ConversionCwd=$conversionCwd;Run=$run;StartedUtc=$startedUtc}
    $measured=Measure-LaTeXAICondition @measureArgs
    return (Complete-LaTeXAICondition -Status $measured.Status -Counts $measured.Counts -Details $measured.Details -Stores $measured.Stores)
}
catch {
    $failureDetails=@{workerError=$_.Exception.Message}
    $failureCounts=@{}
    if($null -ne $nativeResult){
        $failureCounts.timedOut=[int]$nativeResult.TimedOut
        if($null -ne $nativeResult.ExitCode){$failureCounts.exitCode=$nativeResult.ExitCode}
        $failureDetails.nativeOutcome=$nativeResult.Outcome
        $failureDetails.nativeExitCode=$nativeResult.ExitCode
        $failureDetails.nativeCleanupComplete=$nativeResult.CleanupComplete
    }
    return (Complete-LaTeXAICondition -Status 'failed' -Counts $failureCounts -Details $failureDetails -Stores $stores.ToArray())
}

}
