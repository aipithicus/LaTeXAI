#requires -Version 7.5
# Read one recorded condition without interpreting a folder name as its identity.
function Get-LaTeXAIPaperCondition {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$RunPath, [string]$Condition='conversion', [string]$CdxsciRoot='')
    $runtime=Resolve-LaTeXAIRuntime -CdxsciRoot $CdxsciRoot -RequireCdxsci
    Import-Module (Join-Path $runtime.CdxsciRoot 'src/inventory-records/inventory-records.psm1') -Force
    $path=(Resolve-Path -LiteralPath $RunPath).Path
    $record=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json -AsHashtable -DateKind String
    Assert-InventoryRecord $record
    if($record.schema -ne 'codex-scientiae/paper-run/1'){throw 'Expected paper-run/1'}
    if((Get-InventoryFileReference $record.experiment.path).sha256 -cne $record.experiment.sha256){throw 'Changed experiment'}
    $plan=Get-Content -LiteralPath $record.experiment.path -Raw | ConvertFrom-Json -AsHashtable -DateKind String
    Assert-InventoryRecord $plan
    $assignments=@($plan.assignments | Where-Object {$_.jobId -ceq $record.jobId -and $_.attemptId -ceq $record.attemptId})
    if($assignments.Count -ne 1){throw 'Missing or duplicate paper assignment'}
    $read=Read-PaperRun -Path $path -Assignment $assignments[0] -Experiment $record.experiment
    if($record.producer.engine -ne 'latexai' -or $plan.engine -ne 'latexai' -or
        $record.producer.worker.path -cne $plan.worker.path -or $record.producer.worker.sha256 -cne $plan.worker.sha256){throw 'Wrong paper producer'}
    $measurement=if($plan.specification.Contains('measurement')){$plan.specification.measurement}else{$plan.worker}
    if($plan.specification.schema -notin @('latexai/acquisition-plan/1','latexai/paired-plan/1') -or
        $record.payload.measurement.path -cne $measurement.path -or
        $record.payload.measurement.sha256 -cne $measurement.sha256){throw 'Wrong measurement implementation'}
    if(-not (Test-Json -Json ($record.payload | ConvertTo-Json -Depth 100) -SchemaFile (Join-Path $PSScriptRoot 'schemas/paper-experiment.schema.json') -ErrorAction Stop)){throw 'Invalid LaTeXAI payload'}
    if($record.status -eq 'running'){throw 'Paper record is nonterminal'}
    $conditions=@($record.payload.conditions | Where-Object {$_.id -ceq $Condition})
    if($conditions.Count -ne 1){throw 'Missing or duplicate condition'}
    $selected=$conditions[0]
    if(-not $selected.outputs.Contains('xml')){throw 'Condition has no XML'}
    $references=@($record.artifacts | Where-Object {$_.path -ceq $selected.outputs.xml})
    if($references.Count -ne 1 -or -not $selected.outputs.xml.StartsWith("conditions/$Condition/",[StringComparison]::Ordinal)){throw 'Unrecorded condition XML'}
    return [pscustomobject]@{
        Record=$record;Condition=$selected;Reference=$read.Reference
        XmlPath=[IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetDirectoryName($path)) $selected.outputs.xml));XmlSha256=$references[0].sha256
        Experiment=$record.experiment
    }
}
