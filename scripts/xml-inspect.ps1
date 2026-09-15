#requires -Version 7.5
<# Namespace-aware XmlReader prototype over retained ltx XML.
   External resolution disabled. Compares ERROR/Math/dangling/leak counts
   against a recorded condition when supplied. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $XmlPath,
    [string] $RunPath = '',
    [string] $Condition = 'conversion',
    [string] $LegacyReceiptPath = '',
    [string] $CdxsciRoot = '',
    [int] $ExampleLimit = 40
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if($RunPath -and $LegacyReceiptPath){throw 'Choose a paper record or an explicit legacy receipt'}
$ltxNs = 'http://dlmf.nist.gov/LaTeXML'
$settings = [System.Xml.XmlReaderSettings]::new()
$settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
$settings.XmlResolver = $null
$settings.IgnoreComments = $false
$settings.IgnoreWhitespace = $false

$labelSet = [System.Collections.Generic.HashSet[string]]::new()
$labelRefs = [System.Collections.Generic.List[string]]::new()
$errorTexts = [System.Collections.Generic.List[string]]::new()
$leaks = [System.Collections.Generic.List[string]]::new()
$ltxErrors = 0
$mathElements = 0
$completed = $false
$started = [Diagnostics.Stopwatch]::StartNew()
$reader = $null
try {
    $reader = [System.Xml.XmlReader]::Create((Resolve-Path -LiteralPath $XmlPath).Path, $settings)
    while ($reader.Read()) {
        if ($reader.NodeType -eq [System.Xml.XmlNodeType]::Text -or
                $reader.NodeType -eq [System.Xml.XmlNodeType]::CDATA) {
            if ($reader.Value -match '\\lx@[A-Za-z@]*') {
                foreach ($m in [regex]::Matches($reader.Value, '\\lx@[A-Za-z@]*')) { $leaks.Add($m.Value) }
            }
            continue
        }
        if ($reader.NodeType -ne [System.Xml.XmlNodeType]::Element) { continue }
        $ns = [string]$reader.NamespaceURI
        $local = [string]$reader.LocalName
        if ($ns -eq $ltxNs -and $local -eq 'ERROR') {
            $ltxErrors++
            $inner = $reader.ReadString()
            if ($inner) { $errorTexts.Add($inner.Trim()) }
        }
        elseif ($ns -eq $ltxNs -and $local -eq 'Math') { $mathElements++ }
        if ($reader.HasAttributes) {
            while ($reader.MoveToNextAttribute()) {
                if ($reader.LocalName -eq 'labels') {
                    foreach ($token in ($reader.Value -split '\s+')) { if ($token) { [void]$labelSet.Add($token) } }
                }
                elseif ($reader.LocalName -eq 'labelref') {
                    foreach ($token in ($reader.Value -split '\s+')) { if ($token) { $labelRefs.Add($token) } }
                }
                elseif ($reader.Value -match '\\lx@[A-Za-z@]*') {
                    foreach ($m in [regex]::Matches($reader.Value, '\\lx@[A-Za-z@]*')) { $leaks.Add($m.Value) }
                }
            }
            [void]$reader.MoveToElement()
        }
    }
    $completed = $true
}
finally {
    if ($reader) { $reader.Dispose() }
    $started.Stop()
}

$dangling = [System.Collections.Generic.List[string]]::new()
foreach ($token in $labelRefs) {
    if (-not $labelSet.Contains($token)) { $dangling.Add($token) }
}

$report = [ordered]@{
    schema = 'latexai/xml-inspect/0.2'
    xml = (Resolve-Path -LiteralPath $XmlPath).Path
    completed = $completed
    durationMs = [math]::Round($started.Elapsed.TotalMilliseconds, 2)
    workingSetBytes = [System.GC]::GetTotalMemory($false)
    counts = [ordered]@{
        ltxErrors = $ltxErrors
        mathElements = $mathElements
        danglingRefs = $dangling.Count
        internalLeaks = $leaks.Count
    }
    errorNodes = @($errorTexts | Sort-Object -Unique | Select-Object -First $ExampleLimit)
    danglingRefs = @($dangling | Sort-Object -Unique | Select-Object -First $ExampleLimit)
    internalLeaks = @($leaks | Sort-Object -Unique | Select-Object -First $ExampleLimit)
}

if ($RunPath -or $LegacyReceiptPath) {
    if($RunPath){
        . (Join-Path $PSScriptRoot 'latexai-common.ps1')
        . (Join-Path $PSScriptRoot 'gauntlet-records.ps1')
        $evidence=Get-LaTeXAIPaperCondition -RunPath $RunPath -Condition $Condition -CdxsciRoot $CdxsciRoot
        if($evidence.XmlPath -cne (Resolve-Path -LiteralPath $XmlPath).Path){throw 'XML does not belong to the selected condition'}
        $counts=$evidence.Condition.counts
        $report.evidence=@{format='paper-run';record=$evidence.Reference;condition=$Condition;xmlSha256=$evidence.XmlSha256}
    }else{
        $receipt=Get-Content -LiteralPath $LegacyReceiptPath -Raw | ConvertFrom-Json -DateKind String
        if($receipt.schema -ne 'codex-scientiae/inventory-receipt/0.1'){throw 'Unexpected legacy receipt'}
        $counts=$receipt.counts
        $report.evidence=@{format='legacy';path=$LegacyReceiptPath;sha256=(Get-FileHash -LiteralPath $LegacyReceiptPath).Hash.ToLowerInvariant()}
    }
    $report.differences = [ordered]@{
        ltxErrors = [int]$counts.ltxErrors - $ltxErrors
        mathElements = [int]$counts.mathElements - $mathElements
        danglingRefs = [int]$counts.danglingRefs - $dangling.Count
        internalLeaks = [int]$counts.internalLeaks - $leaks.Count
    }
}

$report | ConvertTo-Json -Depth 6
if (-not $completed) { exit 2 }
