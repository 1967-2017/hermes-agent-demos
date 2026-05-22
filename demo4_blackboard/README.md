# Demo 4: Multi-Agent Blackboard arXiv Review

Demo 4 builds a Hermes-native multi-agent workflow with three agents:

- Researcher searches arXiv through MCP tools and writes structured notes.
- Critic checks coverage, contradictions, and citation accuracy, then writes `approve` feedback.
- Writer produces an approximately 2000 Chinese character mini-review from the blackboard.

Agents do not call each other directly. Every handoff is appended to `demo4_blackboard/data/runs/<session>/blackboard.jsonl` with at least `from`, `to`, `round`, `type`, and `content`.
The live viewer shows both agent collaboration messages and tool call traces by default. Setting `DEMO4_ENABLE_VIEWER_LOGS=0` only disables the extra viewer event logs (`agent_status` / `tool_call` / `tool_result`); the viewer still reconstructs collaboration state and tool activity from core handoff records and `research_notes.tool_trace`.

## Environment

Use the requested Conda environment:

```powershell
conda activate hermes-demos
```

Set chat model credentials in `.env` or the shell:

```powershell
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=
```

Demo 4 launches the arXiv MCP server over stdio. Defaults:

```powershell
DEMO4_MCP_COMMAND=uvx
DEMO4_MCP_ARGS=arxiv-mcp-server
DEMO4_ARXIV_STORAGE_PATH=demo4_blackboard/data/arxiv
DEMO4_ARXIV_USER_AGENT=hermes-agent-demos/0.1 (contact: 1654104930@qq.com)
DEMO4_HTTP_MIN_INTERVAL_SECONDS=3.5
DEMO4_ENFORCE_ARXIV_POLICY=1
DEMO4_UV_CACHE_DIR=demo4_blackboard/data/uv-cache
DEMO4_UV_TOOL_DIR=demo4_blackboard/data/uv-tools
DEMO4_MCP_TIMEOUT_SECONDS=300
```

If `uvx` is not available, install the arXiv MCP server in `hermes-demos` and set `DEMO4_MCP_COMMAND` / `DEMO4_MCP_ARGS` to the matching command.
`DEMO4_UV_CACHE_DIR` and `DEMO4_UV_TOOL_DIR` default to repo-local writable directories to avoid permission issues in user-level uv locations.
The first `uvx arxiv-mcp-server` run may take a few minutes while dependencies download; increase `DEMO4_MCP_TIMEOUT_SECONDS` if needed.
Strict mode is enabled by default. Demo 4 always sets a contactable arXiv `User-Agent` and clamps the minimum outbound arXiv request interval to at least 3.0 seconds. The default is 3.5 seconds per HTTP request to stay above the arXiv floor.

## Run

First check that the MCP server can start through `uvx`:

```powershell
conda run -n hermes-demos python -m demo4_blackboard.check_mcp
```

Expected output includes `ok: true` and tools such as `search_papers`, `download_paper`, and `read_paper`.

```powershell
conda run -n hermes-demos python -m demo4_blackboard.main --topic "retrieval augmented generation evaluation methods"
```

Or run the Makefile target:

```powershell
make demo4
```

The controller runs up to 6 rounds. It stops only after Critic returns `approve=true` for two consecutive review messages. If the round limit or timeout is reached, Writer still produces a final review beginning with `未达共识`.

## Replay

```powershell
conda run -n hermes-demos python replay.py --topic "retrieval augmented generation evaluation methods"
```

Use `--json` to print raw blackboard records.

## Verify

```powershell
conda run -n hermes-demos python -m demo4_blackboard.verify --scenario coverage
conda run -n hermes-demos python -m demo4_blackboard.verify --scenario all
```

`verify` writes `demo4_blackboard/VALIDATION_REPORT.md`. Real MCP runs require network access and a working arXiv MCP command.
