# tools/dev/latexai-aliases.ps1
#
# Development-loop wrappers for the LaTeXAI engine. Dot-sourced by
# tools/dev/profile.ps1, which the pwsh_exec MCP server loads via
# MCP_POWERSHELL_PROFILE. Nothing here is needed to build an installable
# distribution; that path is Makefile.PL and blib/, untouched.
#
# The repository root is derived from this file's location, so the loop holds
# for any checkout path. The only machine-specific fact is PERL_ROOT (the
# portable Strawberry Perl root), read from the environment the MCP config sets.
# Ambient PATH is bypassed on purpose: MSYS and the Bash tool resolve a
# different perl first, and stock LaTeXML is not installed anywhere.

$script:LaTeXAIRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$script:LaTeXAILib  = Join-Path $script:LaTeXAIRoot 'lib'
$script:LaTeXAIBin  = Join-Path $script:LaTeXAIRoot 'bin'
# Logs are grouped by run: temp/logs/<runstamp>/. The stamp is LATEXAI_RUNSTAMP
# when the caller set one (so a batch of commands shares a directory), else it
# is minted when this file loads. Under the pwsh_exec MCP that is once per
# command, since the server starts a fresh pwsh each time; set the variable in
# the same command string to group several invocations.
$script:LaTeXAIRunStamp = if ($env:LATEXAI_RUNSTAMP) { $env:LATEXAI_RUNSTAMP } else { Get-Date -Format 'yyyyMMdd_HHmmss' }
$script:LaTeXAILogs = Join-Path $script:LaTeXAIRoot "temp\logs\$script:LaTeXAIRunStamp"
$script:LaTeXAIGen  = Join-Path $script:LaTeXAIRoot 'tools\dev\generate.pl'
$script:LaTeXAICtan = Join-Path $script:LaTeXAIRoot 'tools\dev\fetch-ctan.pl'
$script:LaTeXAIGold = Join-Path $script:LaTeXAIRoot 'tools\dev\golden.pl'
$script:LaTeXAIKatex = Join-Path $script:LaTeXAIRoot 'tools\dev\vendor-katex.pl'

$script:PerlRoot = $env:PERL_ROOT
if (-not $script:PerlRoot -and $env:PERL_HOME) {
    $script:PerlRoot = Split-Path -Parent $env:PERL_HOME
}
if (-not $script:PerlRoot) {
    Write-Warning "latexai-aliases: PERL_ROOT (or PERL_HOME) is not set; lxml/ltst/lmath/lgen will not work in this session."
}
$script:StrawberryPerl = Join-Path $script:PerlRoot 'perl\bin\perl.exe'
# The plain prove script, run through our perl. prove.bat re-locates itself
# through PATH (perl -S), which fails whenever Strawberry is not on PATH; the
# whole point of these wrappers is to never depend on PATH.
$script:ProveScript    = Join-Path $script:PerlRoot 'perl\bin\prove'
# Not machine-specific: the checkout's kpsewhich shim. Pathname.pm reads
# LATEXML_KPSEWHICH when it loads, so this must be set before any perl starts.
$script:Kpsewhich = Join-Path $script:LaTeXAIRoot 'tools\dev\kpsewhich.cmd'
if (Test-Path -LiteralPath $script:Kpsewhich) {
    $env:LATEXML_KPSEWHICH = $script:Kpsewhich
    # lib-ctan/ls-R is the whole answer; a cache miss is definitive. Do not
    # spawn cmd+perl per FindFile miss (the batch pays this on every missing file).
    $env:LATEXML_KPSEWHICH_CACHE_ONLY = '1'
}

function Get-LaTeXAIRoot { $script:LaTeXAIRoot }
function Get-LaTeXAIRunStamp { $script:LaTeXAIRunStamp }

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
function Invoke-LaTeXML     { & $script:StrawberryPerl -I $script:LaTeXAILib (Join-Path $script:LaTeXAIBin 'latexml')     @(Add-LaTeXAILogDefault $args) }
function Invoke-LaTeXMLPost { & $script:StrawberryPerl -I $script:LaTeXAILib (Join-Path $script:LaTeXAIBin 'latexmlpost') @(Add-LaTeXAILogDefault $args) }
function Invoke-LaTeXMLC    { & $script:StrawberryPerl -I $script:LaTeXAILib (Join-Path $script:LaTeXAIBin 'latexmlc')    @(Add-LaTeXAILogDefault $args) }

# Test runner: Strawberry's prove with the LaTeXAI lib on the include path.
# Bespoke drivers read LATEXAI_RUNSTAMP so their logs join this run's directory.
function Invoke-LaTeXMLTest {
    $env:LATEXAI_RUNSTAMP = $script:LaTeXAIRunStamp
    & $script:StrawberryPerl $script:ProveScript -I $script:LaTeXAILib @args
}

# Regenerate MathGrammar.pm and Version.pm into lib/ (idempotent; --force to redo).
function Invoke-LaTeXAIGenerate { & $script:StrawberryPerl $script:LaTeXAIGen @args }

# Vendor packages into lib-ctan/<pkg>/ (CTAN metadata + TeX Live runfiles + provenance).
function Invoke-LaTeXAIFetchCtan { & $script:StrawberryPerl $script:LaTeXAICtan @args }

# Write a fixture's golden with the test driver's own configuration (refuses on errors).
function Invoke-LaTeXAIGolden { & $script:StrawberryPerl $script:LaTeXAIGold @args }

# Vendor a pinned KaTeX clone into lib-katex/ and derive the reference tables.
function Invoke-LaTeXAIVendorKatex { & $script:StrawberryPerl $script:LaTeXAIKatex @args }

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
        'lxml'  = 'Invoke-LaTeXML'        # latexml -I lib [args]      (log -> temp/logs/)
        'lxmlp' = 'Invoke-LaTeXMLPost'    # latexmlpost                (log -> temp/logs/)
        'lxmlc' = 'Invoke-LaTeXMLC'       # latexmlc                   (log -> temp/logs/)
        'ltst'  = 'Invoke-LaTeXMLTest'    # prove -I lib [drivers]
        'lgen'  = 'Invoke-LaTeXAIGenerate' # perl tools/dev/generate.pl [--force]
        'lctan' = 'Invoke-LaTeXAIFetchCtan' # perl tools/dev/fetch-ctan.pl [opts] <pkg>...
        'lgold'  = 'Invoke-LaTeXAIGolden'     # perl tools/dev/golden.pl [--force] t/<suite>/<case>.tex
        'lkatex' = 'Invoke-LaTeXAIVendorKatex' # perl tools/dev/vendor-katex.pl --clone|--restore|--derive|--check
        'lrun'   = 'New-LaTeXAIRun'           # start a named run: logs group under temp/logs/<stamp>/
        'lmath'  = 'Test-LaTeXMLMath'         # probe a math literal
    }
}

(Get-LaTeXAIAliases).GetEnumerator() | ForEach-Object {
    New-Alias -Name $_.Key -Value $_.Value -Scope Global -Force
}
