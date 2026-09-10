#requires -Version 7.5
# Observed-route package selection over retained gauntlet receipts.
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
        [ValidateSet('binding', 'raw', 'raw-local', 'missing', 'union')] [string] $Route = 'union'
    )
    $evidenceRoot = (Resolve-Path -LiteralPath $EvidenceDirectory).Path
    $inventory = Get-LaTeXAIInventoryRows -CdxsciRoot $CdxsciRoot
    $bySlug = @{}
    foreach ($row in $inventory.Rows) { $bySlug[$row.Slug] = $row }

    $receipts = @(Get-ChildItem -LiteralPath $evidenceRoot -Filter receipt.json -Recurse -File)
    $selected = [System.Collections.Generic.List[object]]::new()
    $excluded = [System.Collections.Generic.List[object]]::new()
    $unmatched = [System.Collections.Generic.List[string]]::new()
    $observed = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $selectedSlugs = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

    foreach ($file in $receipts) {
        $receipt = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json -DateKind String
        if ($receipt.schema -ne 'codex-scientiae/inventory-receipt/0.1') { continue }
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
            $excluded.Add([ordered]@{ slug = $slug; reason = 'not-in-canonical-inventory'; receipt = $file.FullName })
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
            receipt = $file.FullName
        })
    }

    $inventorySlugs = @($inventory.Rows | ForEach-Object Slug)
    $missingEvidence = @($inventorySlugs | Where-Object { -not $observed.Contains($_) })

    return [ordered]@{
        schema = 'latexai/gauntlet-package-selection/0.1'
        basis = 'observed-route-receipts'
        incomplete = $true
        incompleteness = 'Selection uses retained route receipts only. Articles without evidence are not negative package-use observations. Subset results support iteration only.'
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
