# PowerShell workflows

## Setup and preview

Use PowerShell 7.5+. Copy the relevant root template to its ignored local location:
`.mcp.example.json` → `.mcp.json`, `.codex.example.toml` → `.codex/config.toml`, or
`.grok.example.toml` → `.grok/config.toml`. Replace placeholders, including the restored
CPython version. Launch the owned Python executable; `uv` is restore-only.

Keep `MCP_POWERSHELL_PROFILE` pointed at this checkout's `scripts/profile.ps1`.
Set `PERL_ROOT` (Strawberry root) and `CDXSCI_ROOT` through the caller environment,
or copy [`scripts/local.example.psd1`](../../scripts/local.example.psd1) to
`scripts/local.psd1` and remove those template env entries. Resolution is argument →
environment → local file. The profile derives `LATEXAI_ROOT` and `PERL_HOME`;
only batch workflows require `CDXSCI_ROOT`. Machine paths stay in ignored files.

Reconnect MCP after changing its registration or server code. Send short commands through
`run_powershell` with an explicit checkout `cwd`: `lgen` after cloning or grammar edits,
`lcfg` for runtimes, and `ltbatch -Selection math -Preview` or `lgauntlet -Preview`
for budgets and job addresses. Previews write metadata but start no workers.
The [alias reference](../../AGENTS.md#2-development-loop) covers individual commands.

## Long work

Call the MCP tool `start_powershell` with arguments such as:

```json
{
  "code": "ltbatch -Selection math -NativeTimeoutSeconds 900 -ExecutionTimeoutSeconds 1200 -WaitTimeoutSeconds 1200 -CleanupTimeoutSeconds 15",
  "cwd": "<LATEXAI_ROOT>",
  "output_directory": "<LATEXAI_ROOT>/temp/logs/<new-run-id>/mcp",
  "timeout_seconds": 1350
}
```

Use a new absolute output directory. Poll `wait_powershell` with the returned `id` and
`wait_seconds: 20` (maximum). To stop, call `cancel_powershell`, then wait for the terminal
result and inspect `success`, `outcome` and `cleanup.status`. Full MCP streams and
`result.json` live in the requested directory; jobs stop when the server shuts down.
These are MCP tool calls, not PowerShell commands. Keep dependent shell commands in
one invocation: each start/run gets a fresh process.

Both batch callers accept a native limit and a separate `-ProcessTimeoutSeconds`;
the worker default is native + 60 seconds. `-ExecutionTimeoutSeconds` and
`-WaitTimeoutSeconds` bound the batch; `-CleanupTimeoutSeconds` bounds executor cleanup.
Choose the outer MCP budget to include preflight, execution, cleanup and receipt writing.
Defaults live in [`scripts/policy.psd1`](../../scripts/policy.psd1).

`run_powershell` defaults to 30 seconds; TOML templates allow 90 seconds per request.
Polling does not reset a job's budget. MCP cleanup has its own 30-second allowance.
Native `0` disables the native and default worker limits; batch limits still apply.
An unbounded MCP run requires explicit `unbounded: true`.

Native supervision uses Windows Job Objects and streams full output to requested files,
retaining at most 1 MiB per stream in memory. Its helper cache is ignored under
`temp/native/`. Aliases fail on nonzero exit, timeout or incomplete cleanup. See
[testing](../testing.md#6-running) for TAP evidence and infrastructure qualification.
