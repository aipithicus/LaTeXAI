#requires -Version 7.5
# Observed-route package selection over retained paper conditions.
# Does not reconstruct membership from demand-join aggregates.

function Get-LaTeXAIInventoryRows {
    param([Parameter(Mandatory)] [string] $CdxsciRoot)
    $inventory = Join-Path $CdxsciRoot 'supellex\gauntlet\inventory.jsonl'
    if (-not (Test-Path -LiteralPath $inventory -PathType Leaf)) {
        throw "canonical inventory not found: '$inventory'"
    }
    $header = $null
    $rows = [System.Collections.Generic.List[object]]::new()
    foreach ($line in [System.IO.File]::ReadLines($inventory)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $obj = $line | ConvertFrom-Json -DateKind String
        if ($obj.PSObject.Properties['__type__'] -and $obj.__type__ -eq 'header') {
            $header = $obj
            continue
        }
        $tree = @($obj.source_forms | Where-Object { $_.role -eq 'latex-source-tree' } | Select-Object -First 1)
        $rows.Add([pscustomobject]@{
            Slug = [string]$obj.slug
            Entrypoint = if ($tree) { [string]$tree.entrypoint } else { $null }
            TreeSha256 = if ($tree) { [string]$tree.sha256 } else { $null }
            TreePath = if ($tree) { [string]$tree.path } else { $null }
            Record = $obj
        })
    }
    return [pscustomobject]@{
        Path = (Resolve-Path -LiteralPath $inventory).Path
        Sha256 = Get-LaTeXAIFileSha256 -Path $inventory
        Header = $header
        Rows = $rows.ToArray()
    }
}

function Test-LaTeXAIPackageMatch {
    param([string] $ObservedName, [string[]] $Wanted)
    $observed = [System.IO.Path]::GetFileNameWithoutExtension($ObservedName)
    foreach ($item in $Wanted) {
        $want = [System.IO.Path]::GetFileNameWithoutExtension($item)
        if ([string]::Equals($observed, $want, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
        if ([string]::Equals($ObservedName, $item, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Test-LaTeXAIRouteMatch {
    param([string] $Route, [string] $Basis)
    switch ($Basis) {
        'binding' { return $Route -eq 'binding' }
        'raw' { return $Route -like 'raw*' }
        'raw-local' { return $Route -eq 'raw-local' }
        'missing' { return $Route -eq 'missing' }
        'union' { return $true }
        default { return $true }
    }
}

function Select-LaTeXAIGauntletPackage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $CdxsciRoot,
        [Parameter(Mandatory)] [string] $EvidenceDirectory,
        [Parameter(Mandatory)] [string[]] $Package,
        [ValidateSet('binding', 'raw', 'raw-local', 'missing', 'union')] [string] $Route = 'union',
        [switch] $LegacyInventory
    )
    $evidenceRoot = (Resolve-Path -LiteralPath $EvidenceDirectory).Path
    $inventory = Get-LaTeXAIInventoryRows -CdxsciRoot $CdxsciRoot
    $bySlug = @{}
    foreach ($row in $inventory.Rows) { $bySlug[$row.Slug] = $row }

    $receipts = [Collections.Generic.List[object]]::new()
    $inputs = [ordered]@{}
    if ($LegacyInventory) {
        foreach ($file in Get-ChildItem -LiteralPath $evidenceRoot -Filter receipt.json -Recurse -File) {
            $record = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json -DateKind String
            if ($record.schema -ne 'codex-scientiae/inventory-receipt/0.1') { throw "Unexpected legacy receipt: $($file.FullName)" }
            $inputs[$file.FullName] = Get-LaTeXAIFileSha256 $file.FullName
            $receipts.Add([pscustomobject]@{FullName=$file.FullName;Receipt=$record;Condition='legacy'})
        }
    } else {
        Import-Module (Join-Path $CdxsciRoot 'src/inventory-records/inventory-records.psm1') -Force
        $batch=Read-InventoryBatch -RunDirectory $evidenceRoot
        foreach($reference in @($batch.Reference,$batch.Record.experiment,$batch.Record.executor)){$inputs[$reference.path]=$reference.sha256}
        foreach($paper in $batch.Papers) {
            $record=$paper.Record
            if($record.payload.schema -ne 'latexai/paper-experiment/1'){throw 'Expected LaTeXAI paper experiment'}
            if(-not (Test-Json -Json ($record.payload | ConvertTo-Json -Depth 100) -SchemaFile (Join-Path $PSScriptRoot 'schemas/paper-experiment.schema.json') -ErrorAction Stop)){throw 'Invalid LaTeXAI paper payload'}
            $inputs[$paper.Reference.path]=$paper.Reference.sha256
            foreach($condition in $record.payload.conditions) {
                if(-not $condition.details.Contains('packages')){continue}
                $receipts.Add([pscustomobject]@{
                    FullName=$paper.Reference.path;Condition=$condition.id
                    Receipt=[pscustomobject]@{article=[pscustomobject]$record.article;entrypoint=$record.article.entrypoint;details=[pscustomobject]$condition.details}
                })
            }
        }
    }
    $selected = [System.Collections.Generic.List[object]]::new()
    $excluded = [System.Collections.Generic.List[object]]::new()
    $unmatched = [System.Collections.Generic.List[string]]::new()
    $observed = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $selectedSlugs = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

    foreach ($file in $receipts) {
        $receipt = $file.Receipt
        $slug = [string]$receipt.article.slug
        [void]$observed.Add($slug)
        $packages = @($receipt.details.packages)
        $hits = @($packages | Where-Object {
                (Test-LaTeXAIPackageMatch -ObservedName $_.name -Wanted $Package) -and
                (Test-LaTeXAIRouteMatch -Route $_.route -Basis $Route)
            })
        if ($hits.Count -eq 0) {
            if (-not $selectedSlugs.Contains($slug)) { $unmatched.Add($slug) }
            continue
        }
        if (-not $selectedSlugs.Add($slug)) { continue }
        $row = $bySlug[$slug]
        if (-not $row) {
            $excluded.Add([ordered]@{ slug = $slug; reason = 'not-in-canonical-inventory'; record = $file.FullName })
            continue
        }
        if ($row.TreeSha256 -and $receipt.article.treeSha256 -and
                -not [string]::Equals($row.TreeSha256, [string]$receipt.article.treeSha256, [System.StringComparison]::OrdinalIgnoreCase)) {
            $excluded.Add([ordered]@{
                slug = $slug; reason = 'stale-tree-hash'
                inventoryTree = $row.TreeSha256; receiptTree = [string]$receipt.article.treeSha256
            })
            continue
        }
        $articleDirectory = [string]$receipt.article.directory
        if (-not (Test-Path -LiteralPath $articleDirectory -PathType Container)) {
            $relative = $row.TreePath
            if ($relative) {
                $articleDirectory = Join-Path $CdxsciRoot ('supellex\gauntlet\' + ($relative -replace '/', [IO.Path]::DirectorySeparatorChar))
                $articleDirectory = Split-Path -Parent $articleDirectory
            }
        }
        if (-not (Test-Path -LiteralPath $articleDirectory -PathType Container)) {
            $excluded.Add([ordered]@{ slug = $slug; reason = 'article-directory-missing' })
            continue
        }
        $selected.Add([ordered]@{
            slug = $slug
            path = (Resolve-Path -LiteralPath $articleDirectory).Path
            entrypoint = [string]$receipt.entrypoint
            treeSha256 = [string]$receipt.article.treeSha256
            routes = @($hits | ForEach-Object { [ordered]@{ name = $_.name; route = $_.route } })
            record = $file.FullName
            condition = $file.Condition
        })
    }

    $inventorySlugs = @($inventory.Rows | ForEach-Object Slug)
    $missingEvidence = @($inventorySlugs | Where-Object { -not $observed.Contains($_) })

    return [ordered]@{
        schema = 'latexai/gauntlet-package-selection/0.2'
        basis = ($LegacyInventory ? 'legacy-receipts' : 'paper-conditions')
        inputs = $inputs
        incomplete = $true
        incompleteness = 'Selection uses retained route observations only. Articles without evidence are not negative package-use observations. Subset results support iteration only.'
        packages = @($Package)
        route = $Route
        evidenceDirectory = $evidenceRoot
        inventory = [ordered]@{
            path = $inventory.Path
            sha256 = $inventory.Sha256
            count = $inventory.Rows.Count
        }
        selected = $selected.ToArray()
        excluded = $excluded.ToArray()
        missingEvidenceCount = $missingEvidence.Count
        observedUnmatched = @($unmatched | Select-Object -Unique)
        selectedCount = $selected.Count
        excludedCount = $excluded.Count
        observedCount = $observed.Count
    }
}
