#requires -Version 7.5
# scripts/latexai-common.ps1
#
# Shared resolver for the LaTeXAI development loop. Profile, aliases, gauntlet
# and test callers all derive the checkout from this file's location and resolve
# machine bindings with the same precedence: explicit invocation, then nonblank
# caller environment, then scripts/local.psd1. This file never reads MCP JSON
# or TOML, never falls back to a remembered host path, and never discovers Perl
# through PATH.

Set-StrictMode -Version Latest

$script:LaTeXAIMinimumPowerShell = [version]'7.5'
$script:LaTeXAIChildVersionCache = @{}
$script:LaTeXAILocalConfigNames = @('PERL_ROOT', 'CDXSCI_ROOT')

function Get-LaTeXAICheckoutRoot {
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
}

function Test-LaTeXAIPowerShellVersion {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [version] $Version,
        [Parameter(Mandatory)] [string] $Label,
        [string] $Executable = ''
    )
    if ($Version -lt $script:LaTeXAIMinimumPowerShell) {
        $where = if ($Executable) { "$Label ($Executable)" } else { $Label }
        throw ("LaTeXAI requires PowerShell {0} or newer; {1} is {2}." -f
            $script:LaTeXAIMinimumPowerShell, $where, $Version)
    }
}

function Get-LaTeXAIHostPowerShellPath {
    (Get-Process -Id $PID).Path
}

function Get-LaTeXAIPowerShellIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Executable,
        [switch] $CurrentHost
    )
    $resolved = [System.IO.Path]::GetFullPath($Executable)
    if ($CurrentHost) {
        Test-LaTeXAIPowerShellVersion -Version $PSVersionTable.PSVersion -Label 'host' -Executable $resolved
        return [ordered]@{
            Executable = $resolved
            PSVersion = $PSVersionTable.PSVersion.ToString()
            PSEdition = [string]$PSVersionTable.PSEdition
            GitCommit = [string]$PSVersionTable['GitCommit']
            DotNet = [System.Runtime.InteropServices.RuntimeInformation]::FrameworkDescription
            Source = 'host'
        }
    }
    if ($script:LaTeXAIChildVersionCache.ContainsKey($resolved)) {
        $cached = $script:LaTeXAIChildVersionCache[$resolved]
        Test-LaTeXAIPowerShellVersion -Version ([version]$cached.PSVersion) -Label 'child' -Executable $resolved
        return $cached
    }
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "LaTeXAI: PowerShell executable not found: '$resolved'"
    }
    $psi = [System.Diagnostics.ProcessStartInfo]::new($resolved)
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.ArgumentList.Add('-NoProfile')
    $psi.ArgumentList.Add('-Command')
    $psi.ArgumentList.Add(@'
$info = [ordered]@{
    PSVersion = $PSVersionTable.PSVersion.ToString()
    PSEdition = [string]$PSVersionTable.PSEdition
    GitCommit = [string]$PSVersionTable['GitCommit']
    DotNet = [System.Runtime.InteropServices.RuntimeInformation]::FrameworkDescription
}
$info | ConvertTo-Json -Compress
'@)
    $process = [System.Diagnostics.Process]::Start($psi)
    try {
        if (-not $process.WaitForExit(15000)) {
            try { $process.Kill($true) } catch { }
            throw "LaTeXAI: timed out querying PowerShell version of '$resolved'"
        }
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        if ($process.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($stdout)) {
            throw ("LaTeXAI: failed to query PowerShell version of '{0}' (exit {1}): {2}{3}" -f
                $resolved, $process.ExitCode, $stdout, $stderr)
        }
        $parsed = $stdout | ConvertFrom-Json
        $identity = [ordered]@{
            Executable = $resolved
            PSVersion = [string]$parsed.PSVersion
            PSEdition = [string]$parsed.PSEdition
            GitCommit = [string]$parsed.GitCommit
            DotNet = [string]$parsed.DotNet
            Source = 'child-preflight'
        }
        Test-LaTeXAIPowerShellVersion -Version ([version]$identity.PSVersion) -Label 'child' -Executable $resolved
        $script:LaTeXAIChildVersionCache[$resolved] = $identity
        return $identity
    }
    finally { $process.Dispose() }
}

function Import-LaTeXAILocalConfig {
    $path = Join-Path $PSScriptRoot 'local.psd1'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return [ordered]@{ Present = $false; Path = $path; Data = @{} }
    }
    $data = Import-PowerShellDataFile -LiteralPath $path
    if ($data -isnot [System.Collections.IDictionary]) {
        throw "LaTeXAI: scripts/local.psd1 must be a hashtable (see scripts/local.example.psd1)."
    }
    foreach ($key in @($data.Keys)) {
        if ($key -notin $script:LaTeXAILocalConfigNames) {
            Write-Warning ("LaTeXAI: scripts/local.psd1 key '{0}' is ignored. Machine bindings are {1}. Operational policy is scripts/policy.psd1." -f
                $key, ($script:LaTeXAILocalConfigNames -join ', '))
        }
    }
    return [ordered]@{ Present = $true; Path = $path; Data = $data }
}

function Get-LaTeXAIPolicy {
    $path = Join-Path $PSScriptRoot 'policy.psd1'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "LaTeXAI: tracked policy file missing: '$path'"
    }
    $policy = Import-PowerShellDataFile -LiteralPath $path
    if ($policy -isnot [System.Collections.IDictionary]) {
        throw "LaTeXAI: scripts/policy.psd1 must be a hashtable."
    }
    return $policy
}

function Resolve-LaTeXAIConfiguredValue {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Name,
        [string] $Explicit,
        [Parameter(Mandatory)] [string] $EnvironmentName,
        [System.Collections.IDictionary] $Local,
        [switch] $Required,
        [string] $Need = ''
    )
    $localValue = ''
    if ($null -ne $Local -and $Local.ContainsKey($Name)) {
        $localValue = [string]$Local[$Name]
    }
    $envValue = [string][System.Environment]::GetEnvironmentVariable($EnvironmentName)
    $value = $null
    $source = 'unset'
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
        $value = $Explicit.Trim()
        $source = 'explicit'
    }
    elseif (-not [string]::IsNullOrWhiteSpace($envValue)) {
        $value = $envValue.Trim()
        $source = 'environment'
    }
    elseif (-not [string]::IsNullOrWhiteSpace($localValue)) {
        $value = $localValue.Trim()
        $source = 'local'
    }
    if ([string]::IsNullOrWhiteSpace($value)) {
        if ($Required) {
            $for = if ($Need) { " Needed for: $Need." } else { '' }
            throw ("LaTeXAI: {0} is not set. Pass -{0}, export {1}, or add {0} to scripts/local.psd1 (see scripts/local.example.psd1).{2}" -f
                $Name, $EnvironmentName, $for)
        }
        return [ordered]@{
            Name = $Name; Value = $null; Source = 'unset'
            Environment = $envValue; Local = $localValue
        }
    }
    return [ordered]@{
        Name = $Name; Value = $value; Source = $source
        Environment = $envValue; Local = $localValue
    }
}

function Resolve-LaTeXAIPerlRoot {
    param([Parameter(Mandatory)] [string] $PerlRoot, [Parameter(Mandatory)] [string] $Source)
    if (-not (Test-Path -LiteralPath $PerlRoot -PathType Container)) {
        throw "LaTeXAI: PERL_ROOT from $Source is not a directory: '$PerlRoot'"
    }
    $resolved = (Resolve-Path -LiteralPath $PerlRoot).Path
    $perl = Join-Path $resolved 'perl\bin\perl.exe'
    if (-not (Test-Path -LiteralPath $perl -PathType Leaf)) {
        throw "LaTeXAI: Strawberry perl not found under PERL_ROOT from ${Source}: '$perl'"
    }
    return [ordered]@{
        PerlRoot = $resolved
        PerlHome = Join-Path $resolved 'perl'
        PerlPath = (Resolve-Path -LiteralPath $perl).Path
        ProveScript = Join-Path $resolved 'perl\bin\prove'
        Source = $Source
    }
}

function Resolve-LaTeXAICdxsciRoot {
    param([Parameter(Mandatory)] [string] $CdxsciRoot, [Parameter(Mandatory)] [string] $Source)
    if (-not (Test-Path -LiteralPath $CdxsciRoot -PathType Container)) {
        throw "LaTeXAI: CDXSCI_ROOT from $Source is not a directory: '$CdxsciRoot'"
    }
    $resolved = (Resolve-Path -LiteralPath $CdxsciRoot).Path
    $executor = Join-Path $resolved 'src\batch-executor\batch-executor.psd1'
    $runner = Join-Path $resolved 'src\batch-runner.ps1'
    if (-not (Test-Path -LiteralPath $executor -PathType Leaf)) {
        throw "LaTeXAI: CDXSCI_ROOT from $Source has no batch executor: '$executor'"
    }
    if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
        throw "LaTeXAI: CDXSCI_ROOT from $Source has no inventory runner: '$runner'"
    }
    return [ordered]@{
        CdxsciRoot = $resolved
        ExecutorManifest = (Resolve-Path -LiteralPath $executor).Path
        AdaptersManifest = (Resolve-Path -LiteralPath (Join-Path $resolved 'src\batch-adapters\adapters.psd1')).Path
        BatchRunner = (Resolve-Path -LiteralPath $runner).Path
        Source = $Source
    }
}

function Get-LaTeXAIFileSha256 {
    param([Parameter(Mandatory)] [string] $Path)
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-LaTeXAITrackedScriptIdentity {
    param([string] $CheckoutRoot = (Get-LaTeXAICheckoutRoot))
    $policy = Get-LaTeXAIPolicy
    $rows = [System.Collections.Generic.List[object]]::new()
    foreach ($relative in @($policy.ScriptIdentity)) {
        $path = Join-Path $CheckoutRoot ($relative -replace '/', [System.IO.Path]::DirectorySeparatorChar)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $rows.Add([ordered]@{ path = $relative; present = $false; sha256 = $null })
            continue
        }
        $rows.Add([ordered]@{
            path = $relative
            present = $true
            sha256 = Get-LaTeXAIFileSha256 -Path $path
        })
    }
    return $rows.ToArray()
}

function Resolve-LaTeXAIRuntime {
    [CmdletBinding()]
    param(
        [string] $PerlRoot,
        [string] $CdxsciRoot,
        [string] $PowerShellExecutable,
        [switch] $RequirePerl,
        [switch] $RequireCdxsci
    )
    Test-LaTeXAIPowerShellVersion -Version $PSVersionTable.PSVersion -Label 'host' -Executable (Get-LaTeXAIHostPowerShellPath)
    $checkout = Get-LaTeXAICheckoutRoot
    $local = Import-LaTeXAILocalConfig
    $perlBinding = Resolve-LaTeXAIConfiguredValue -Name 'PERL_ROOT' -Explicit $PerlRoot `
        -EnvironmentName 'PERL_ROOT' -Local $local.Data -Required:$RequirePerl `
        -Need 'direct engine commands, tests and gauntlet conversions'
    $cdxsciBinding = Resolve-LaTeXAIConfiguredValue -Name 'CDXSCI_ROOT' -Explicit $CdxsciRoot `
        -EnvironmentName 'CDXSCI_ROOT' -Local $local.Data -Required:$RequireCdxsci `
        -Need 'gauntlet and TAP test batches'
    $psBinding = Resolve-LaTeXAIConfiguredValue -Name 'LATEXAI_POWERSHELL' -Explicit $PowerShellExecutable `
        -EnvironmentName 'LATEXAI_POWERSHELL' -Local @{} -Required:$false
    $hostPath = Get-LaTeXAIHostPowerShellPath
    $childPath = if ($psBinding.Value) { $psBinding.Value } else { $hostPath }
    $childPath = [System.IO.Path]::GetFullPath($childPath)
    $hostIdentity = Get-LaTeXAIPowerShellIdentity -Executable $hostPath -CurrentHost
    $childIdentity = if ([string]::Equals($childPath, $hostPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        $hostIdentity
    }
    else {
        Get-LaTeXAIPowerShellIdentity -Executable $childPath
    }

    $perl = $null
    if ($perlBinding.Value) {
        $perl = Resolve-LaTeXAIPerlRoot -PerlRoot $perlBinding.Value -Source $perlBinding.Source
    }
    $cdxsci = $null
    if ($cdxsciBinding.Value) {
        $cdxsci = Resolve-LaTeXAICdxsciRoot -CdxsciRoot $cdxsciBinding.Value -Source $cdxsciBinding.Source
    }

    $kpsewhich = Join-Path $checkout 'scripts\kpsewhich.cmd'
    $generated = @(
        Join-Path $checkout 'lib\LaTeXML\Version.pm'
        Join-Path $checkout 'lib\LaTeXML\MathGrammar.pm'
    ) | ForEach-Object {
        [ordered]@{
            path = [System.IO.Path]::GetRelativePath($checkout, $_) -replace '\\', '/'
            present = [bool](Test-Path -LiteralPath $_ -PathType Leaf)
        }
    }

    return [ordered]@{
        CheckoutRoot = $checkout
        LibDirectory = Join-Path $checkout 'lib'
        BinDirectory = Join-Path $checkout 'bin'
        ScriptsDirectory = $PSScriptRoot
        PreloadDirectory = Join-Path $PSScriptRoot 'preloads'
        GenerateScript = Join-Path $checkout 'tools\dev\generate.pl'
        TapRunScript = Join-Path $checkout 'tools\dev\tap-run.pl'
        Kpsewhich = $kpsewhich
        KpsewhichPresent = [bool](Test-Path -LiteralPath $kpsewhich -PathType Leaf)
        PerlRoot = if ($perl) { $perl.PerlRoot } else { $null }
        PerlHome = if ($perl) { $perl.PerlHome } else { $null }
        PerlPath = if ($perl) { $perl.PerlPath } else { $null }
        ProveScript = if ($perl) { $perl.ProveScript } else { $null }
        PerlRootSource = $perlBinding.Source
        CdxsciRoot = if ($cdxsci) { $cdxsci.CdxsciRoot } else { $null }
        CdxsciRootSource = $cdxsciBinding.Source
        ExecutorManifest = if ($cdxsci) { $cdxsci.ExecutorManifest } else { $null }
        AdaptersManifest = if ($cdxsci) { $cdxsci.AdaptersManifest } else { $null }
        BatchRunner = if ($cdxsci) { $cdxsci.BatchRunner } else { $null }
        LocalConfig = [ordered]@{
            Present = [bool]$local.Present
            Path = $local.Path
        }
        HostPowerShell = $hostIdentity
        ChildPowerShell = $childIdentity
        ChildPowerShellSource = if ($psBinding.Value) { $psBinding.Source } else { 'host' }
        GeneratedModules = @($generated)
        Policy = Get-LaTeXAIPolicy
        TrackedScripts = @(Get-LaTeXAITrackedScriptIdentity -CheckoutRoot $checkout)
    }
}

function Set-LaTeXAIRuntimeEnvironment {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [System.Collections.IDictionary] $Runtime,
        [switch] $IncludeCdxsci
    )
    if ($Runtime.PerlRoot) {
        $env:PERL_ROOT = $Runtime.PerlRoot
        $env:PERL_HOME = $Runtime.PerlHome
    }
    $env:LATEXAI_ROOT = $Runtime.CheckoutRoot
    if ($Runtime.KpsewhichPresent) {
        $env:LATEXML_KPSEWHICH = $Runtime.Kpsewhich
        $env:LATEXML_KPSEWHICH_CACHE_ONLY = '1'
    }
    if ($IncludeCdxsci -and $Runtime.CdxsciRoot) {
        $env:CDXSCI_ROOT = $Runtime.CdxsciRoot
    }
}

function Show-LaTeXAIRuntime {
    [CmdletBinding()]
    param(
        [string] $PerlRoot,
        [string] $CdxsciRoot,
        [string] $PowerShellExecutable,
        [switch] $RequirePerl,
        [switch] $RequireCdxsci
    )
    $runtime = Resolve-LaTeXAIRuntime -PerlRoot $PerlRoot -CdxsciRoot $CdxsciRoot `
        -PowerShellExecutable $PowerShellExecutable -RequirePerl:$RequirePerl -RequireCdxsci:$RequireCdxsci
    $policy = $runtime.Policy
    $view = [ordered]@{
        checkout = $runtime.CheckoutRoot
        powershell = [ordered]@{
            host = $runtime.HostPowerShell
            child = $runtime.ChildPowerShell
            childSource = $runtime.ChildPowerShellSource
            minimum = [string]$policy.PowerShellMinimumVersion
        }
        perl = [ordered]@{
            root = $runtime.PerlRoot
            home = $runtime.PerlHome
            executable = $runtime.PerlPath
            prove = $runtime.ProveScript
            source = $runtime.PerlRootSource
        }
        cdxsci = [ordered]@{
            root = $runtime.CdxsciRoot
            source = $runtime.CdxsciRootSource
            executor = $runtime.ExecutorManifest
        }
        kpsewhich = $runtime.Kpsewhich
        generatedModules = $runtime.GeneratedModules
        localConfig = $runtime.LocalConfig
        budgets = [ordered]@{
            direct = $policy.Direct
            markdown = $policy.Markdown
            gauntlet = $policy.Gauntlet
            test = $policy.Test.Budgets
        }
        testSelections = @($policy.Test.Selections.Keys)
        trackedScripts = $runtime.TrackedScripts
    }
    $view | ConvertTo-Json -Depth 8
}

function Get-LaTeXAINativeTimeoutSeconds {
    [CmdletBinding()]
    param(
        [string] $Family = 'Direct',
        [nullable[int]] $Override = $null
    )
    if ($null -ne $Override) { return [int]$Override }
    $envValue = [string][System.Environment]::GetEnvironmentVariable('LATEXAI_NATIVE_TIMEOUT')
    if (-not [string]::IsNullOrWhiteSpace($envValue)) { return [int]$envValue }
    $policy = Get-LaTeXAIPolicy
    switch ($Family) {
        'Markdown' { return [int]$policy.Markdown.TimeoutSeconds }
        'Gauntlet' { return [int]$policy.Gauntlet.NativeTimeoutSeconds }
        'Test' { return [int]$policy.Test.Budgets.ProcessTimeoutSeconds }
        default { return [int]$policy.Direct.TimeoutSeconds }
    }
}

function Invoke-LaTeXAINative {
    <# Bounded native launch. The wait loop uses WaitForExit(slice) on the host
       thread so pipeline stop remains possible. Timeout 0 is an explicit
       unbounded diagnostic. Descendants are killed with Process.Kill(true).
       Stream drain after stop has its own cleanup budget. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $FilePath,
        [AllowEmptyCollection()] [string[]] $Arguments = @(),
        [string] $WorkingDirectory = '',
        [int] $TimeoutSeconds = -1,
        [int] $CleanupTimeoutSeconds = -1,
        [int] $WaitSliceMilliseconds = -1,
        [string] $StdOutPath = '',
        [string] $StdErrPath = '',
        [switch] $SamplePeakWorkingSet
    )
    $policy = Get-LaTeXAIPolicy
    if ($TimeoutSeconds -lt 0) { $TimeoutSeconds = [int]$policy.Direct.TimeoutSeconds }
    if ($CleanupTimeoutSeconds -lt 0) { $CleanupTimeoutSeconds = [int]$policy.Direct.CleanupTimeoutSeconds }
    if ($WaitSliceMilliseconds -lt 0) { $WaitSliceMilliseconds = [int]$policy.Direct.WaitSliceMilliseconds }
    if ($WaitSliceMilliseconds -lt 1) { $WaitSliceMilliseconds = 50 }

    $started = [datetime]::UtcNow
    $result = [ordered]@{
        FilePath = $FilePath
        Arguments = @($Arguments)
        WorkingDirectory = $WorkingDirectory
        ExitCode = $null
        TimedOut = $false
        Outcome = 'failed-to-launch'
        CleanupComplete = $false
        StdOut = ''
        StdErr = ''
        DurationMs = 0
        PeakWorkingSetBytes = $null
        TimeoutSecondsRequested = $TimeoutSeconds
        TimeoutSecondsEffective = $TimeoutSeconds
        CleanupTimeoutSeconds = $CleanupTimeoutSeconds
        SampledPeakWorkingSet = [bool]$SamplePeakWorkingSet
    }
    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        $result.StdErr = "executable not found: '$FilePath'"
        $result.DurationMs = [math]::Round(([datetime]::UtcNow - $started).TotalMilliseconds, 2)
        return [pscustomobject]$result
    }
    $psi = [System.Diagnostics.ProcessStartInfo]::new($FilePath)
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $psi.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    foreach ($argument in @($Arguments)) { $psi.ArgumentList.Add($argument) }
    if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }

    $process = $null
    try {
        $process = [System.Diagnostics.Process]::Start($psi)
    }
    catch {
        $result.StdErr = $_.Exception.Message
        $result.DurationMs = [math]::Round(([datetime]::UtcNow - $started).TotalMilliseconds, 2)
        return [pscustomobject]$result
    }

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $deadline = if ($TimeoutSeconds -gt 0) { $started.AddSeconds($TimeoutSeconds) } else { [datetime]::MaxValue }
    $peak = $null
    try {
        while (-not $process.HasExited) {
            if ([datetime]::UtcNow -ge $deadline) {
                $result.TimedOut = $true
                try { $process.Kill($true) } catch { }
                break
            }
            if ($SamplePeakWorkingSet) {
                try {
                    $process.Refresh()
                    $observed = $process.PeakWorkingSet64
                    if ($null -eq $peak -or $observed -gt $peak) { $peak = $observed }
                }
                catch { }
            }
            [void]$process.WaitForExit($WaitSliceMilliseconds)
        }
        if (-not $process.HasExited) {
            $cleanupDeadline = [datetime]::UtcNow.AddSeconds([math]::Max(1, $CleanupTimeoutSeconds))
            while (-not $process.HasExited -and [datetime]::UtcNow -lt $cleanupDeadline) {
                [void]$process.WaitForExit($WaitSliceMilliseconds)
            }
        }
        $result.CleanupComplete = [bool]$process.HasExited
        if ($process.HasExited) { $result.ExitCode = $process.ExitCode }
        $drainMs = [math]::Max(1, $CleanupTimeoutSeconds) * 1000
        [void][System.Threading.Tasks.Task]::WaitAll(@($stdoutTask, $stderrTask), $drainMs)
        if ($stdoutTask.IsCompletedSuccessfully) { $result.StdOut = [string]$stdoutTask.Result }
        elseif ($stdoutTask.IsCompleted) {
            try { $result.StdOut = [string]$stdoutTask.GetAwaiter().GetResult() } catch { $result.StdOut = '' }
        }
        if ($stderrTask.IsCompletedSuccessfully) { $result.StdErr = [string]$stderrTask.Result }
        elseif ($stderrTask.IsCompleted) {
            try { $result.StdErr = [string]$stderrTask.GetAwaiter().GetResult() } catch { }
        }
        if ($SamplePeakWorkingSet -and $process.HasExited) {
            try {
                $process.Refresh()
                $finalPeak = $process.PeakWorkingSet64
                if ($null -eq $peak -or $finalPeak -gt $peak) { $peak = $finalPeak }
            }
            catch { }
        }
        $result.PeakWorkingSetBytes = $peak
        $result.Outcome = if ($result.TimedOut) {
            if ($result.CleanupComplete) { 'timed-out' } else { 'timed-out-cleanup-incomplete' }
        }
        elseif (-not $result.CleanupComplete) { 'cleanup-incomplete' }
        else { 'exited' }
    }
    finally {
        if ($process) { $process.Dispose() }
    }
    $result.DurationMs = [math]::Round(([datetime]::UtcNow - $started).TotalMilliseconds, 2)
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    if ($StdOutPath) {
        $outDir = [System.IO.Path]::GetDirectoryName($StdOutPath)
        if ($outDir) { [void][System.IO.Directory]::CreateDirectory($outDir) }
        [System.IO.File]::WriteAllText($StdOutPath, [string]$result.StdOut, $utf8)
    }
    if ($StdErrPath) {
        $errDir = [System.IO.Path]::GetDirectoryName($StdErrPath)
        if ($errDir) { [void][System.IO.Directory]::CreateDirectory($errDir) }
        [System.IO.File]::WriteAllText($StdErrPath, [string]$result.StdErr, $utf8)
    }
    return [pscustomobject]$result
}

function Write-LaTeXAINativeStreams {
    param([Parameter(Mandatory)] $Run)
    if ($Run.StdOut) { Write-Output $Run.StdOut }
    if ($Run.StdErr) { [Console]::Error.Write($Run.StdErr) }
    if ($null -ne $Run.ExitCode) { $global:LASTEXITCODE = [int]$Run.ExitCode }
    else { $global:LASTEXITCODE = -1 }
    if ($Run.TimedOut) {
        throw ("LaTeXAI native timeout after {0}s: {1}" -f $Run.TimeoutSecondsEffective, $Run.FilePath)
    }
    if ($Run.Outcome -eq 'failed-to-launch') {
        throw ("LaTeXAI native launch failed: {0}: {1}" -f $Run.FilePath, $Run.StdErr)
    }
}

