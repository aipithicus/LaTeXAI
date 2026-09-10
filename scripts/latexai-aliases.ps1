#requires -Version 7.5
# scripts/latexai-aliases.ps1
#
# Development-loop wrappers for the LaTeXAI engine. Dot-sourced by
# scripts/profile.ps1, which the pwsh_exec MCP server loads via
# MCP_POWERSHELL_PROFILE. Nothing here is needed to build an installable
# distribution; that path is Makefile.PL and blib/, untouched.
#
# The repository root is derived from scripts/latexai-common.ps1. PERL_ROOT is
# resolved by that helper (explicit, environment, then scripts/local.psd1).
# Ambient PATH is bypassed on purpose: MSYS and the Bash tool resolve a
# different perl first, and stock LaTeXML is not installed anywhere.

if (-not (Get-Command -Name Resolve-LaTeXAIRuntime -ErrorAction SilentlyContinue)) {
    . (Join-Path $PSScriptRoot 'latexai-common.ps1')
}
if (-not $script:LaTeXAIRuntime) {
    $script:LaTeXAIRuntime = Resolve-LaTeXAIRuntime -RequirePerl
    Set-LaTeXAIRuntimeEnvironment -Runtime $script:LaTeXAIRuntime
}

$script:LaTeXAIRoot = $script:LaTeXAIRuntime.CheckoutRoot
$script:LaTeXAILib = $script:LaTeXAIRuntime.LibDirectory
$script:LaTeXAIBin = $script:LaTeXAIRuntime.BinDirectory
# Logs are grouped by run: temp/logs/<runstamp>/. The stamp is LATEXAI_RUNSTAMP
# when the caller set one (so a batch of commands shares a directory), else it
# is minted when this file loads. Under the pwsh_exec MCP that is once per
# command, since the server starts a fresh pwsh each time; set the variable in
# the same command string to group several invocations.
$script:LaTeXAIRunStamp = if ($env:LATEXAI_RUNSTAMP) { $env:LATEXAI_RUNSTAMP } else { Get-Date -Format 'yyyyMMdd_HHmmss' }
$script:LaTeXAILogs = Join-Path $script:LaTeXAIRoot "temp\logs\$script:LaTeXAIRunStamp"
$script:LaTeXAIGen = $script:LaTeXAIRuntime.GenerateScript
$script:LaTeXAICtan = Join-Path $script:LaTeXAIRoot 'tools\dev\fetch-ctan.pl'
$script:LaTeXAIGold = Join-Path $script:LaTeXAIRoot 'tools\dev\golden.pl'
$script:LaTeXAIKatex = Join-Path $script:LaTeXAIRoot 'tools\dev\vendor-katex.pl'
$script:LaTeXAISymb = Join-Path $script:LaTeXAIRoot 'tools\dev\symbind.pl'
$script:StrawberryPerl = $script:LaTeXAIRuntime.PerlPath
$script:ProveScript = $script:LaTeXAIRuntime.ProveScript
$script:Kpsewhich = $script:LaTeXAIRuntime.Kpsewhich
$script:LaTeXAITestRun = Join-Path $PSScriptRoot 'test-run.ps1'
$script:LaTeXAIGauntletRun = Join-Path $PSScriptRoot 'gauntlet-run.ps1'

function Get-LaTeXAIRoot { $script:LaTeXAIRoot }
function Get-LaTeXAIRunStamp { $script:LaTeXAIRunStamp }
function Get-LaTeXAIRuntime { $script:LaTeXAIRuntime }

# Start a named run: every alias and every test driver in this process (and in
# child processes) logs under temp/logs/<stamp>/ until the process ends.
function New-LaTeXAIRun {
    param([string]$Stamp = (Get-Date -Format 'yyyyMMdd_HHmmss'))
    $env:LATEXAI_RUNSTAMP = $Stamp
    $script:LaTeXAIRunStamp = $Stamp
    $script:LaTeXAILogs = Join-Path $script:LaTeXAIRoot "temp\logs\$Stamp"
    return $Stamp
}

# latexml names its log after the job: <source-basename>.latexml.log, or
# latexml.log for a literal. Reproduce that so every CLI run lands in
# temp/logs/ unless the caller passed --log explicitly.
function script:Add-LaTeXAILogDefault {
    param([string[]]$CliArgs)
    if ($CliArgs | Where-Object { $_ -like '--log=*' -or $_ -eq '--log' }) { return $CliArgs }
    $source = $CliArgs | Where-Object { $_ -notlike '-*' } | Select-Object -First 1
    $job = 'latexml'
    if ($source -and $source -notlike 'literal:*') {
        $job = [System.IO.Path]::GetFileNameWithoutExtension($source)
        if (-not $job) { $job = 'latexml' }
    }
    New-Item -ItemType Directory -Force -Path $script:LaTeXAILogs | Out-Null
    return @("--log=$(Join-Path $script:LaTeXAILogs "$job.latexml.log")") + $CliArgs
}

# Core engine CLIs, run from lib/ only. generate.pl puts the compiled grammar
# and the stamped version module in lib/, so no second include path is needed.
function Invoke-LaTeXML { & $script:StrawberryPerl -I $script:LaTeXAILib (Join-Path $script:LaTeXAIBin 'latexml')     @(Add-LaTeXAILogDefault $args) }
function Invoke-LaTeXMLPost { & $script:StrawberryPerl -I $script:LaTeXAILib (Join-Path $script:LaTeXAIBin 'latexmlpost') @(Add-LaTeXAILogDefault $args) }
function Invoke-LaTeXMLC { & $script:StrawberryPerl -I $script:LaTeXAILib (Join-Path $script:LaTeXAIBin 'latexmlc')    @(Add-LaTeXAILogDefault $args) }

# Test runner: Strawberry's prove with the LaTeXAI lib on the include path.
# Bespoke drivers read LATEXAI_RUNSTAMP so their logs join this run's directory.
function Invoke-LaTeXMLTest {
    $env:LATEXAI_RUNSTAMP = $script:LaTeXAIRunStamp
    & $script:StrawberryPerl $script:ProveScript -I $script:LaTeXAILib @args
}

# Parallel TAP batches through the shared executor. Requires CDXSCI_ROOT.
function Invoke-LaTeXAITestBatch {
    & $script:LaTeXAITestRun @args
}

function Invoke-LaTeXAIGauntlet {
    & $script:LaTeXAIGauntletRun @args
}

function Show-LaTeXAIConfig {
    Show-LaTeXAIRuntime @args
}

# Regenerate MathGrammar.pm and Version.pm into lib/ (idempotent; --force to redo).
function Invoke-LaTeXAIGenerate { & $script:StrawberryPerl $script:LaTeXAIGen @args }

# Vendor packages into lib-ctan/<pkg>/ (CTAN metadata + TeX Live runfiles + provenance).
function Invoke-LaTeXAIFetchCtan { & $script:StrawberryPerl $script:LaTeXAICtan @args }

# Write a fixture's golden with the test driver's own configuration (refuses on errors).
function Invoke-LaTeXAIGolden { & $script:StrawberryPerl $script:LaTeXAIGold @args }

# Vendor a pinned KaTeX clone into lib-katex/ and derive the reference tables.
function Invoke-LaTeXAIVendorKatex { & $script:StrawberryPerl $script:LaTeXAIKatex @args }

# Extract, author, seed, check, or generate notation tables under lib-symb/.
function Invoke-LaTeXAISymbind { & $script:StrawberryPerl $script:LaTeXAISymb @args }

# Quick math probe.
function Test-LaTeXMLMath {
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Expression,
        [string]$Preload,
        [switch]$Capture,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Rest
    )
    $cmdArgs = @()
    if ($Preload) { $cmdArgs += "--preload=$Preload" }
    if ($Capture) { $cmdArgs += '--capture' }
    if ($Rest) { $cmdArgs += $Rest }
    $cmdArgs += "literal:$Expression"
    Invoke-LaTeXML @cmdArgs
}

function Get-LaTeXAIAliases {
    return @{
        'lxml'     = 'Invoke-LaTeXML'          # latexml -I lib [args]      (log -> temp/logs/)
        'lxmlp'    = 'Invoke-LaTeXMLPost'      # latexmlpost                (log -> temp/logs/)
        'lxmlc'    = 'Invoke-LaTeXMLC'         # latexmlc                   (log -> temp/logs/)
        'ltst'     = 'Invoke-LaTeXMLTest'      # prove -I lib [drivers]
        'ltbatch'  = 'Invoke-LaTeXAITestBatch' # scripts/test-run.ps1 [opts]
        'lgauntlet'= 'Invoke-LaTeXAIGauntlet'  # scripts/gauntlet-run.ps1 [opts]
        'lcfg'     = 'Show-LaTeXAIConfig'      # runtime/selection preview; no lgen or tests
        'lgen'     = 'Invoke-LaTeXAIGenerate'  # perl tools/dev/generate.pl [--force]
        'lctan'    = 'Invoke-LaTeXAIFetchCtan' # perl tools/dev/fetch-ctan.pl [opts] <pkg>...
        'lgold'    = 'Invoke-LaTeXAIGolden'    # perl tools/dev/golden.pl [--force] t/<suite>/<case>.tex
        'lkatex'   = 'Invoke-LaTeXAIVendorKatex' # perl tools/dev/vendor-katex.pl --clone|--restore|--derive|--check
        'lsymb'    = 'Invoke-LaTeXAISymbind'   # perl tools/dev/symbind.pl --extract|--author|--seed-katex|--check|--generate
        'lrun'     = 'New-LaTeXAIRun'          # start a named run: logs group under temp/logs/<stamp>/
        'lmath'    = 'Test-LaTeXMLMath'        # probe a math literal
    }
}

(Get-LaTeXAIAliases).GetEnumerator() | ForEach-Object {
    New-Alias -Name $_.Key -Value $_.Value -Scope Global -Force
}
