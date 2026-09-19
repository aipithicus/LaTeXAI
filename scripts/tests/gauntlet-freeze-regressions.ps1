#requires -Version 7.5
# Verify the byte-level fingerprint contract independently of traversal/hash code.
[CmdletBinding()]
param([string] $RunDirectory = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $root 'scripts/latexai-common.ps1')
$config = Resolve-LaTeXAIRuntime -RequireCdxsci
Import-Module (Join-Path $config.CdxsciRoot 'src/inventory-records/inventory-records.psm1') -Force
. (Join-Path $root 'scripts/gauntlet-freeze.ps1')
if (-not $RunDirectory) {
    $RunDirectory = Join-Path $root ('temp/t/gauntlet-freeze/' + [guid]::NewGuid().ToString('N'))
}
if (Test-Path -LiteralPath $RunDirectory) { throw 'Choose a new regression directory' }
$RunDirectory = [IO.Path]::GetFullPath($RunDirectory)
$tree = Join-Path $RunDirectory 'tree'
[void][IO.Directory]::CreateDirectory($tree)
$checks = 0
function Assert-Fingerprint([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw $Message }
    $script:checks++
}
function Hash-Bytes([byte[]] $Bytes) {
    [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()
}
function Assert-Rejected([scriptblock] $Action, [string] $Pattern, [string] $Message) {
    $errorText = ''
    try { $null = & $Action } catch { $errorText = $_.Exception.ToString() }
    Assert-Fingerprint ($errorText.Length -gt 0 -and $errorText -like $Pattern) $Message
}

$empty = Get-LaTeXAITreeRecord $tree
Assert-Fingerprint ($empty.count -eq 0) 'Empty tree has no file rows'
Assert-Fingerprint ($empty.sha256 -ceq 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855') 'Empty canonical stream hash'
$fixture = [ordered]@{
    '.hidden' = [Text.Encoding]::UTF8.GetBytes("hidden`n")
    'Z.txt' = [byte[]]@()
    'nested/binary.bin' = [byte[]](0..131070 | ForEach-Object { $_ % 256 })
    'nested/é space.tex' = [Text.Encoding]::UTF8.GetBytes("αβ`r`nzero`0tail")
    'a.txt' = [Text.Encoding]::UTF8.GetBytes('literal bytes')
}
foreach ($name in $fixture.Keys) {
    $path = Join-Path $tree $name
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path))
    [IO.File]::WriteAllBytes($path, $fixture[$name])
}
if ($IsWindows) {
    $hidden = Join-Path $tree '.hidden'
    [IO.File]::SetAttributes($hidden, [IO.File]::GetAttributes($hidden) -bor [IO.FileAttributes]::Hidden)
}
$names = [string[]]@($fixture.Keys)
[Array]::Sort($names, [StringComparer]::Ordinal)
$canonical = [Text.StringBuilder]::new()
foreach ($name in $names) {
    [void]$canonical.Append($name).Append([char]0).Append($fixture[$name].Length).Append([char]0).Append((Hash-Bytes $fixture[$name])).Append("`n")
}
$wanted = Hash-Bytes ([Text.Encoding]::UTF8.GetBytes($canonical.ToString()))
$actual = Get-LaTeXAITreeRecord $tree
Assert-Fingerprint ($actual.count -eq $fixture.Count) 'Include hidden, empty, binary and nested files'
Assert-Fingerprint ($actual.sha256 -ceq $wanted) 'Canonical fingerprint agrees with literal fixture bytes'
Assert-Fingerprint ($actual.root -ceq (Resolve-Path -LiteralPath $tree).Path) 'Root address remains resolved'
for ($i = 0; $i -lt $names.Count; $i++) {
    $name = $names[$i]; $row = $actual.files[$i]
    Assert-Fingerprint ($row.path -ceq $name -and $row.bytes -eq $fixture[$name].Length -and $row.sha256 -ceq (Hash-Bytes $fixture[$name])) "Exact ordinal file row: $name"
}
Assert-Fingerprint ((Get-LaTeXAITreeRecord $tree).sha256 -ceq $wanted) 'Repeated verification remains stable'
$binary = Join-Path $tree 'nested/binary.bin'
$stamp = [IO.File]::GetLastWriteTimeUtc($binary)
$changed = [byte[]]$fixture['nested/binary.bin'].Clone()
$changed[65536] = $changed[65536] -bxor 255
[IO.File]::WriteAllBytes($binary, $changed)
[IO.File]::SetLastWriteTimeUtc($binary, $stamp)
Assert-Fingerprint ((Get-LaTeXAITreeRecord $tree).sha256 -cne $wanted) 'Same-length content change with restored timestamp is detected'
[IO.File]::WriteAllBytes($binary, $fixture['nested/binary.bin'])
Assert-Fingerprint ((Get-LaTeXAITreeRecord $tree).sha256 -ceq $wanted) 'Restored bytes restore the original fingerprint'
$added = Join-Path $tree 'extra.txt'
[IO.File]::WriteAllText($added, 'extra')
$more = Get-LaTeXAITreeRecord $tree
Assert-Fingerprint ($more.count -eq $fixture.Count + 1 -and $more.sha256 -cne $wanted) 'Added file is detected'
[IO.File]::Delete($added)
Assert-Fingerprint ((Get-LaTeXAITreeRecord $tree).sha256 -ceq $wanted) 'Removed extra file restores the fingerprint'
$renamed = Join-Path $tree 'renamed.txt'
[IO.File]::Move((Join-Path $tree 'a.txt'), $renamed)
Assert-Fingerprint ((Get-LaTeXAITreeRecord $tree).sha256 -cne $wanted) 'A path change is part of the fingerprint'
[IO.File]::Move($renamed, (Join-Path $tree 'a.txt'))
[void][IO.Directory]::CreateDirectory((Join-Path $tree 'empty-directory'))
Assert-Fingerprint ((Get-LaTeXAITreeRecord $tree).sha256 -ceq $wanted) 'Empty directories do not add file rows'
Assert-Rejected { Get-LaTeXAITreeRecord (Join-Path $tree 'absent') } '*' 'Missing root is rejected'
if ($IsWindows) {
    $link = Join-Path $RunDirectory 'root-link'
    $child = Join-Path $tree 'child-link'
    try {
        $null = New-Item -ItemType Junction -Path $link -Target $tree
        Assert-Rejected { Get-LaTeXAITreeRecord $link } '*Linked frozen input*' 'A linked root is rejected'
        $null = New-Item -ItemType Junction -Path $child -Target $tree
        Assert-Rejected { Get-LaTeXAITreeRecord $tree } '*Linked frozen input*' 'A linked child is rejected before following it'
    } finally {
        foreach ($path in @($child, $link)) {
            if (Test-Path -LiteralPath $path) {
                $item = Get-Item -LiteralPath $path -Force
                if (-not $item.FullName.StartsWith($RunDirectory + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
                    -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unexpected link cleanup target' }
                # Delete only the directory link itself; never recurse into its target.
                [IO.Directory]::Delete($item.FullName)
            }
        }
    }
    Assert-Fingerprint ((Get-LaTeXAITreeRecord $tree).sha256 -ceq $wanted) 'Link rejection leaves original bytes intact'
}
Write-Output "PASS: $checks frozen-tree fingerprint regression checks"
