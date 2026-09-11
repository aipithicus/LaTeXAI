#requires -Version 7.5
[CmdletBinding()]
param([string] $RunDirectory = '')
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $root 'scripts/latexai-common.ps1')
if (-not $RunDirectory) {
    $RunDirectory = Join-Path $root ('temp/t/native-regressions/' + [guid]::NewGuid().ToString('N'))
}
[void][IO.Directory]::CreateDirectory($RunDirectory)
$pwsh = Join-Path $PSHOME 'pwsh.exe'
function Assert-Native { param([bool] $Condition, [string] $Message) if (-not $Condition) { throw $Message } }
function Native-Arguments { param([string] $Code) return @('-NoProfile', '-EncodedCommand', [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Code))) }

$out = Join-Path $RunDirectory 'large.stdout'
$err = Join-Path $RunDirectory 'large.stderr'
$run = Invoke-LaTeXAINative -FilePath $pwsh -Arguments (Native-Arguments "[Console]::Out.Write('x' * 2MB); [Console]::Error.Write('y' * 2MB)") `
    -TimeoutSeconds 10 -CleanupTimeoutSeconds 3 -StdOutPath $out -StdErrPath $err
Assert-Native ($run.ExitCode -eq 0 -and $run.CleanupComplete) 'large capture failed'
Assert-Native ($run.StdOutTruncated -and $run.StdErrTruncated) 'capture loss was not reported'
Assert-Native ($run.StdOut.Length -le 1MB -and $run.StdErr.Length -le 1MB) 'memory capture was not bounded'
Assert-Native ((Get-Item $out).Length -eq 2MB -and (Get-Item $err).Length -eq 2MB) 'durable streams lost bytes'

$out = Join-Path $RunDirectory 'timeout.stdout'
$err = Join-Path $RunDirectory 'timeout.stderr'
$run = Invoke-LaTeXAINative -FilePath $pwsh -Arguments (Native-Arguments "[Console]::Out.Write('partial-out'); [Console]::Error.Write('partial-err'); Start-Sleep 30") `
    -TimeoutSeconds 2 -CleanupTimeoutSeconds 3 -StdOutPath $out -StdErrPath $err
Assert-Native ($run.TimedOut -and $run.CleanupComplete) 'timeout cleanup failed'
Assert-Native ([IO.File]::ReadAllText($out) -eq 'partial-out' -and [IO.File]::ReadAllText($err) -eq 'partial-err') 'timeout lost partial streams'

$run = Invoke-LaTeXAINative -FilePath $pwsh -Arguments (Native-Arguments @'
$start = [Diagnostics.ProcessStartInfo]::new((Join-Path $PSHOME 'pwsh.exe'))
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
foreach ($arg in @('-NoProfile', '-Command', 'Start-Sleep 30')) { $start.ArgumentList.Add($arg) }
$child = [Diagnostics.Process]::Start($start)
[Console]::Out.Write($child.Id)
[Environment]::Exit(0)
'@) -TimeoutSeconds 10 -CleanupTimeoutSeconds 3
Assert-Native ($run.ExitCode -eq 0 -and $run.CleanupComplete) 'root-first exit cleanup failed'
Assert-Native ($null -eq (Get-Process -Id ([int]$run.StdOut) -ErrorAction SilentlyContinue)) 'descendant survived root exit'

$pidFile = Join-Path $RunDirectory 'cancel.pid'
$out = Join-Path $RunDirectory 'cancel.stdout'
$pipeline = [PowerShell]::Create()
$async = $null
try {
    [void]$pipeline.AddScript({ param($Common, $Executable, $PidFile, $OutputFile)
        . $Common
        $code = "[IO.File]::WriteAllText('$PidFile', [string]`$PID); [Console]::Out.Write('live'); Start-Sleep 30"
        Invoke-LaTeXAINative -FilePath $Executable -Arguments @('-NoProfile', '-EncodedCommand',
            [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))) `
            -TimeoutSeconds 20 -StdOutPath $OutputFile
    }).AddArgument((Join-Path $root 'scripts/latexai-common.ps1')).AddArgument($pwsh).AddArgument($pidFile).AddArgument($out)
    $async = $pipeline.BeginInvoke()
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while ($watch.Elapsed.TotalSeconds -lt 10 -and (-not [IO.File]::Exists($out) -or (Get-Item $out).Length -eq 0)) {
        Start-Sleep -Milliseconds 50
    }
    Assert-Native ([IO.File]::Exists($pidFile) -and (Get-Item $out).Length -gt 0) 'output was not streamed while running'
    $childId = [int][IO.File]::ReadAllText($pidFile)
    [void]$pipeline.BeginStop($null, $null)
    Assert-Native ($async.AsyncWaitHandle.WaitOne(5000)) 'pipeline cancellation exceeded budget'
    try { $null = $pipeline.EndInvoke($async) } catch [Management.Automation.PipelineStoppedException] {}
    $watch.Restart()
    while ($watch.Elapsed.TotalSeconds -lt 3 -and (Get-Process -Id $childId -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 50 }
    Assert-Native ($null -eq (Get-Process -Id $childId -ErrorAction SilentlyContinue)) 'native process survived caller cancellation'
}
finally { $pipeline.Dispose() }

$run = Invoke-LaTeXAINative -FilePath $pwsh -Arguments (Native-Arguments "exit 7") -TimeoutSeconds 5
$failed = $false
try { Write-LaTeXAINativeStreams -Run $run } catch { $failed = $true }
Assert-Native $failed 'a nonzero native exit was reported as a successful alias call'
[ordered]@{ passed = 5; runDirectory = $RunDirectory } | ConvertTo-Json
