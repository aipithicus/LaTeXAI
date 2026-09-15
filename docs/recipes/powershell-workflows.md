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
the single-condition worker default is native + 60 seconds. `-ExecutionTimeoutSeconds` and
`-WaitTimeoutSeconds` bound the batch; `-CleanupTimeoutSeconds` bounds executor cleanup.
Choose the outer MCP budget to include preflight, execution, cleanup and record publication.
Defaults live in [`scripts/policy.psd1`](../../scripts/policy.psd1).

`run_powershell` defaults to 30 seconds; TOML templates allow 90 seconds per request.
Polling does not reset a job's budget. MCP cleanup has its own 30-second allowance.
Native `0` disables the native and default worker limits; batch limits still apply.
An unbounded MCP run requires explicit `unbounded: true`.

## Paired paper experiments

```powershell
lgauntlet -CaptureParity -Path supellex/gauntlet/<collection>/<paper> `
  -NativeTimeoutSeconds 300 -ComparisonTimeoutSeconds 180 `
  -ProcessTimeoutSeconds 1200 -WaitTimeoutSeconds 1500 `
  -ExecutionTimeoutSeconds 1500 -FailOnArticleFailure
```

Use `-Preview` first for the resolved conditions, order and budgets. The paired
worker deadline defaults to twice (native + 60), plus comparison + 300 seconds
for validation/publication. Native and comparison deadlines must be finite;
the outer MCP budget must also cover input copying before dispatch. The launcher
mints a new artifact run; an explicit `-RunDirectory` must already exist under
CDXSCI artifacts. Existing plans, freezes and terminal records cannot be replaced.

`-OnFirst` records the opposite condition order. `-OffArgument` and `-OnArgument`
add standalone flags; `--capture` is owned by the plan. A deliberate unknown flag
on one side exercises native failure and incomplete comparison without changing
source bytes. Read `batch.json` and its worker `run.json`, including qualification
and cleanup; native completion alone does not establish parity. See the
[record contract](../specification/gauntlet-records.md) for freeze boundaries.

## Analysis and selective retry

```powershell
# Reinspect and compare a frozen paired batch; start no engine conversions.
lgauntlet -ReuseBatch <prior-artifact-directory> -AnalysisOnly -FailOnArticleFailure

# Reuse eligible conditions and execute missing, failed or invalidated conditions.
lgauntlet -ReuseBatch <prior-artifact-directory> -FailOnArticleFailure
```

Both commands mint a new experiment and preserve the prior batch. Selection and
conversion options default to that batch; `-Path` narrows the selection and
explicit conversion options override the defaults. For example, `-OnArgument @()`
clears a deliberate on-side failure flag. `-Preview` shows mode, inputs and budgets.
Analysis-only workers default to comparison + 600 seconds for measurement and
validation; selective retry retains the paired native-budget formula. Input
copying still occurs before dispatch and belongs in the outer MCP budget.

Read `conversionsExecuted`, `conversionsReused` and `conversionsRejected` in the
worker summary. Reused native timing/memory are historical observations in the
condition's conversion origin; current measurement, comparison and total attempt
times remain separate. A changed comparator or extractor reruns analysis; a
changed conversion identity requires conversion or an analysis-only rejection.

Native supervision uses Windows Job Objects and streams full output to requested files,
retaining at most 1 MiB per stream in memory. Its helper cache is ignored under
`temp/native/`. Aliases fail on nonzero exit, timeout or incomplete cleanup. See
[testing](../testing.md#6-running) for TAP evidence and infrastructure qualification.
