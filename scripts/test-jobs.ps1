#requires -Version 7.5
# scripts/test-jobs.ps1 — TAP adapter. Discovers complete t/*.t drivers and
# emits New-BatchJob records. Not a scheduler.

function Get-LaTeXAITestStableHash {
    param(
        [Parameter(Mandatory)] [AllowEmptyString()] [string] $Value,
        [ValidateRange(8, 64)] [int] $Length = 12
    )
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        $hex = [System.Convert]::ToHexString($sha.ComputeHash($bytes)).ToLowerInvariant()
        return $hex.Substring(0, $Length)
    }
    finally { $sha.Dispose() }
}

function ConvertTo-LaTeXAITestAddressLeaf {
    param(
        [Parameter(Mandatory)] [string] $DriverPath,
        [Parameter(Mandatory)] [string] $Digest
    )
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($DriverPath)
    $stem = [regex]::Replace($stem.ToLowerInvariant(), '[^a-z0-9._-]+', '-').Trim('-', '.')
    if ([string]::IsNullOrWhiteSpace($stem)) { $stem = 'test' }
    if ($stem.Length -gt 48) { $stem = $stem.Substring(0, 48).TrimEnd('-', '.') }
    return "$stem-$Digest"
}

function Resolve-LaTeXAITestJobAddress {
    param(
        [Parameter(Mandatory)] [string] $RunDirectory,
        [Parameter(Mandatory)] [string] $AddressLeaf
    )
    $jobDirectory = [System.IO.Path]::Combine($RunDirectory, 'tap-jobs', $AddressLeaf)
    return [pscustomobject]@{
        JobDirectory = $jobDirectory
        ResultPath = [System.IO.Path]::Combine($jobDirectory, 'result.json')
        TapPath = [System.IO.Path]::Combine($jobDirectory, 'tap.txt')
        StdOutPath = [System.IO.Path]::Combine($jobDirectory, 'stdout.txt')
        StdErrPath = [System.IO.Path]::Combine($jobDirectory, 'stderr.txt')
        ArtifactRoot = [System.IO.Path]::Combine($jobDirectory, 'artifacts')
        TempRoot = [System.IO.Path]::Combine($jobDirectory, 'temp')
    }
}

function ConvertTo-LaTeXAIRepoRelative {
    param([Parameter(Mandatory)] [string] $CheckoutRoot, [Parameter(Mandatory)] [string] $Path)
    ([System.IO.Path]::GetRelativePath($CheckoutRoot, $Path) -replace '\\', '/')
}

function Get-LaTeXAILatexmlSuiteWrites {
    param(
        [Parameter(Mandatory)] [string] $CheckoutRoot,
        [Parameter(Mandatory)] [string] $DriverPath
    )
    $writes = [System.Collections.Generic.List[string]]::new()
    $text = [System.IO.File]::ReadAllText($DriverPath)
    foreach ($match in [regex]::Matches($text, 'latexml_tests\(\s*[''"]([^''"]+)[''"]')) {
        $suite = $match.Groups[1].Value -replace '/', [System.IO.Path]::DirectorySeparatorChar
        $writes.Add((Join-Path $CheckoutRoot $suite))
    }
    return $writes.ToArray()
}

function Resolve-LaTeXAITestSelection {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $CheckoutRoot,
        [AllowEmptyCollection()] [string[]] $Path = @(),
        [string] $Selection = ''
    )
    $policy = Get-LaTeXAIPolicy
    $requested = [System.Collections.Generic.List[string]]::new()
    if (-not [string]::IsNullOrWhiteSpace($Selection)) {
        if ($Selection -eq 'full') {
            $requested.Add((Join-Path $CheckoutRoot 't\*.t'))
        }
        elseif ($policy.Test.Selections.ContainsKey($Selection)) {
            foreach ($entry in @($policy.Test.Selections[$Selection])) { $requested.Add($entry) }
        }
        else {
            throw "LaTeXAI test selection '$Selection' is not defined. Known: full, $((@($policy.Test.Selections.Keys) | Sort-Object) -join ', ')"
        }
    }
    foreach ($entry in @($Path)) {
        if ([string]::IsNullOrWhiteSpace($entry)) { continue }
        if ($entry -eq 'full' -or $policy.Test.Selections.ContainsKey($entry)) {
            if ($entry -eq 'full') { $requested.Add((Join-Path $CheckoutRoot 't\*.t')) }
            else { foreach ($item in @($policy.Test.Selections[$entry])) { $requested.Add($item) } }
            continue
        }
        $requested.Add($entry)
    }
    if ($requested.Count -eq 0) {
        throw 'LaTeXAI test selection is empty. Pass -Path, -Selection, or a named list such as math.'
    }

    $resolved = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in $requested) {
        $candidate = $entry
        if (-not [System.IO.Path]::IsPathRooted($candidate)) {
            $candidate = Join-Path $CheckoutRoot ($candidate -replace '/', [System.IO.Path]::DirectorySeparatorChar)
        }
        $parent = Split-Path -Parent $candidate
        $leaf = Split-Path -Leaf $candidate
        $isGlob = $leaf -match '[*?]'
        if ($isGlob) {
            if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
                throw "LaTeXAI test glob parent not found: '$parent' (from '$entry')"
            }
            $matches = @(Get-ChildItem -LiteralPath $parent -Filter $leaf -File | Sort-Object Name)
            if ($matches.Count -eq 0) {
                throw "LaTeXAI test glob matched no drivers: '$entry'"
            }
            foreach ($file in $matches) {
                if ($seen.Add($file.FullName)) { $resolved.Add($file.FullName) }
            }
            continue
        }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "LaTeXAI test driver not found: '$entry'"
        }
        $full = (Resolve-Path -LiteralPath $candidate).Path
        if ($seen.Add($full)) { $resolved.Add($full) }
    }
    if ($resolved.Count -eq 0) {
        throw 'LaTeXAI test discovery produced no drivers.'
    }
    return $resolved.ToArray()
}

function Get-LaTeXAITestJob {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $RunDirectory,
        [Parameter(Mandatory)] [System.Collections.IDictionary] $Runtime,
        [AllowEmptyCollection()] [string[]] $Path = @(),
        [string] $Selection = '',
        [int] $TimeoutSeconds = 0
    )
    $checkout = $Runtime.CheckoutRoot
    $run = [System.IO.Path]::GetFullPath($RunDirectory)
    $worker = Join-Path $PSScriptRoot 'test-worker.ps1'
    if (-not (Test-Path -LiteralPath $worker -PathType Leaf)) {
        throw "TAP worker not found: '$worker'"
    }
    $worker = (Resolve-Path -LiteralPath $worker).Path
    $tapRun = $Runtime.TapRunScript
    if (-not (Test-Path -LiteralPath $tapRun -PathType Leaf)) {
        throw "TAP harness bridge not found: '$tapRun'"
    }
    $policy = $Runtime.Policy
    $drivers = @(Resolve-LaTeXAITestSelection -CheckoutRoot $checkout -Path $Path -Selection $Selection)
    $jobs = [System.Collections.Generic.List[object]]::new()
    foreach ($driver in $drivers) {
        $relative = ConvertTo-LaTeXAIRepoRelative -CheckoutRoot $checkout -Path $driver
        $digest = Get-LaTeXAITestStableHash -Value "path=$relative"
        $id = "tap:$relative#$digest"
        $address = Resolve-LaTeXAITestJobAddress -RunDirectory $run -AddressLeaf (ConvertTo-LaTeXAITestAddressLeaf -DriverPath $driver -Digest $digest)
        $cost = [double]$policy.Test.DefaultEstimatedCost
        if ($policy.Test.EstimatedCost.ContainsKey($relative)) {
            $cost = [double]$policy.Test.EstimatedCost[$relative]
        }
        $writes = [System.Collections.Generic.List[string]]::new()
        foreach ($path in @($address.JobDirectory, $address.ArtifactRoot, $address.TempRoot, $address.ResultPath, $address.TapPath)) {
            $writes.Add($path)
        }
        if ($policy.Test.ExtraWrites.ContainsKey($relative)) {
            foreach ($extra in @($policy.Test.ExtraWrites[$relative])) {
                $writes.Add((Join-Path $checkout ($extra -replace '/', [System.IO.Path]::DirectorySeparatorChar)))
            }
        }
        foreach ($suite in @(Get-LaTeXAILatexmlSuiteWrites -CheckoutRoot $checkout -DriverPath $driver)) {
            $writes.Add($suite)
        }
        $stamp = 't-' + $digest
        $processSpec = @{
            PowerShellPath = $Runtime.ChildPowerShell.Executable
            WorkingDirectory = $checkout
            Environment = @{
                PERL_ROOT = $Runtime.PerlRoot
                PERL_HOME = $Runtime.PerlHome
                LATEXAI_ROOT = $checkout
                LATEXAI_RUNSTAMP = $stamp
                LATEXML_KPSEWHICH = $Runtime.Kpsewhich
                LATEXML_KPSEWHICH_CACHE_ONLY = '1'
                CDXSCI_TEMP = $address.TempRoot
                TEMP = $address.TempRoot
                TMP = $address.TempRoot
                TMPDIR = $address.TempRoot
                HARNESS_OPTIONS = ''
            }
        }
        if ($TimeoutSeconds -gt 0) { $processSpec.TimeoutSeconds = $TimeoutSeconds }
        $metadata = @{
            Domain = 'tap'
            Adapter = 'latexai-tap'
            RepositoryRelativePath = $relative
            SourcePath = $driver
            RunDirectory = $run
            JobDirectory = $address.JobDirectory
            ResultPath = $address.ResultPath
            TapPath = $address.TapPath
            ArtifactRoot = $address.ArtifactRoot
            TempRoot = $address.TempRoot
            RunStamp = $stamp
        }
        $jobs.Add((batch-executor\New-BatchJob -Id $id -Kind PowerShellProcess -EntryPoint $worker `
            -Parameters @{
                Driver = $driver
                ResultPath = $address.ResultPath
                TapPath = $address.TapPath
                StdOutPath = $address.StdOutPath
                StdErrPath = $address.StdErrPath
                CheckoutRoot = $checkout
                PerlPath = $Runtime.PerlPath
                TapRunScript = $tapRun
                LibDirectory = $Runtime.LibDirectory
            } -RuntimeProfile 'latexai-tap' -ProcessSpec $processSpec `
            -EstimatedCost $cost -Writes $writes.ToArray() `
            -WorkingDirectory $checkout -Metadata $metadata))
    }
    return $jobs.ToArray()
}
