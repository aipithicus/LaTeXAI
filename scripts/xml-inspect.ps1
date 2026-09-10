#requires -Version 7.5
<# Namespace-aware XmlReader prototype over retained ltx XML.
   External resolution disabled. Compares ERROR/Math/dangling/leak counts
   against a receipt when one is supplied. Does not replace worker regex
   until differences are classified. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $XmlPath,
    [string] $ReceiptPath = '',
    [int] $ExampleLimit = 40
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
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
    schema = 'latexai/xml-inspect/0.1'
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

if ($ReceiptPath) {
    $receipt = Get-Content -LiteralPath $ReceiptPath -Raw | ConvertFrom-Json -DateKind String
    $report.receipt = $ReceiptPath
    $report.differences = [ordered]@{
        ltxErrors = [int]$receipt.counts.ltxErrors - $ltxErrors
        mathElements = [int]$receipt.counts.mathElements - $mathElements
        danglingRefs = [int]$receipt.counts.danglingRefs - $dangling.Count
        internalLeaks = [int]$receipt.counts.internalLeaks - $leaks.Count
    }
}

$report | ConvertTo-Json -Depth 6
if (-not $completed) { exit 2 }
