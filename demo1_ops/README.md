# Demo 1: Hermes Native Tool-Calling Ops Assistant

This demo implements the Hermes-native protocol explicitly:

- ChatML messages
- system prompt with `<tools>...</tools>`
- assistant tool requests as `<tool_call>{...}</tool_call>`
- local parser/executor loop

It does not use LangChain or the OpenAI tools/function-calling API.

## Run

```bash
python -m demo1_ops.main --scenario 1
python -m demo1_ops.verify
make demo1
```

PowerShell equivalents from the repo root:

```powershell
python -m demo1_ops.main --scenario 1
python -m demo1_ops.verify
```

Run a single Demo 1 scenario from the repo root:

```bash
make demo1-run SCENARIO=4
```

```powershell
python -m demo1_ops.main --scenario 4
```

Run one validation scenario instead of all five:

```bash
make demo1 DEMO1_SCENARIO=3
```

```powershell
python -m demo1_ops.verify --scenario 3
```

Recommended validation commands:

```bash
python -m demo1_ops.verify --scenario 1
python -m demo1_ops.verify --scenario 2a
python -m demo1_ops.verify --scenario 2b
python -m demo1_ops.verify --scenario 6
python -m demo1_ops.verify
```

## Scenario Map

- `1` `metric-query`
  - 查看单个指标，只允许一次 `query_metric`
- `2a` `incident-triage-restart`
  - `query_metric` + `tail_log` 排查后判断需要重启
  - 必须先 `notify_oncall`，再进入重启确认/执行
- `2b` `incident-triage-no-restart`
  - `query_metric` + `tail_log` 排查后判断不需要重启
  - 不能调用 `notify_oncall` 或 `restart_service`
- `3` `restart-rejection`
  - 用户拒绝重启，不能执行 `restart_service(confirm=true)`
- `4` `restart-confirmation`
  - 用户确认后才允许真正重启
- `5` `out-of-scope-refusal`
  - 非运维请求直接拒绝
- `6` `bulk-restart-refusal`
  - “重启所有服务”必须拒绝

## Environment Setup

Create a repo-local `.env` from `.env.example` or export the variables in your shell.

Minimum variables:

```env
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-pro
```

PowerShell example:

```powershell
Get-Content .env | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
  $name, $value = $_ -split '=', 2
  [System.Environment]::SetEnvironmentVariable($name, $value, 'Process')
}
```

## Compliance Check

I checked the current Demo 1 implementation for shortcut logic before updating this file.

- No execution-path branch matches raw user text and returns a hardcoded final answer.
- No execution-path branch matches raw user text and directly selects a tool without the model producing `<tool_call>`.
- Scenario-specific assertions exist only in `verify.py`, which is acceptable because they validate traces rather than drive runtime behavior.
- Service-specific mock data in `tools.py` is acceptable for this demo because the model still decides whether to call `query_metric`, `tail_log`, `notify_oncall`, or `restart_service`.

Required environment variables:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

## Artifacts

- [demo1_ops/data/traces](E:\AAA\Project\hermes-agent\hermes-agent-new\demo1_ops\data\traces)
- [demo1_ops/data/notifications.jsonl](E:\AAA\Project\hermes-agent\hermes-agent-new\demo1_ops\data\notifications.jsonl)
- [demo1_ops/data/verification_report.md](E:\AAA\Project\hermes-agent\hermes-agent-new\demo1_ops\data\verification_report.md)
