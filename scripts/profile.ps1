#requires -Version 7.5
# scripts/profile.ps1
#
# PowerShell profile for the LaTeXAI development loop. The pwsh_exec MCP
# server dot-sources whatever MCP_POWERSHELL_PROFILE names; both .mcp.json and
# .codex/config.toml point it here. Interactive-console furniture (history,
# prompt) is deliberately absent: this runs in a non-interactive child.
# Machine bindings come from the caller environment or scripts/local.psd1.
# Loading this profile does not require CDXSCI_ROOT.

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Set-StrictMode -Version Latest

. (Join-Path $PSScriptRoot 'latexai-common.ps1')
$script:LaTeXAIRuntime = Resolve-LaTeXAIRuntime -RequirePerl
Set-LaTeXAIRuntimeEnvironment -Runtime $script:LaTeXAIRuntime
. (Join-Path $PSScriptRoot 'latexai-aliases.ps1')
