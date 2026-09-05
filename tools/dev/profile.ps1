# tools/dev/profile.ps1
#
# PowerShell profile for the LaTeXAI development loop. The pwsh_exec MCP
# server dot-sources whatever MCP_POWERSHELL_PROFILE names; both .mcp.json and
# .codex/config.toml point it here. Interactive-console furniture (history,
# prompt) is deliberately absent: this runs in a non-interactive child.

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

. (Join-Path $PSScriptRoot 'latexai-aliases.ps1')
