# Demo 2: Hermes Native Travel Planner

Demo 2 implements a two-stage travel planning agent:

- Planner: produces structured JSON plans and replans after every observation.
- Executor: executes exactly one plan step at a time with Hermes native `<tool_call>` blocks.
- Tools: mock travel APIs for flights, hotels, weather, visa/entry feasibility, and budget.

It does not use OpenAI function calling or LangChain. The protocol is explicit ChatML plus Hermes-native tool blocks.

## Run

From the repository root:

```powershell
python -m demo2_travel.main --scenario 1
python -m demo2_travel.verify
```

Manual input uses the same runner as validation scenarios:

```powershell
python -m demo2_travel.main --input "暑假去泰国 5 天，预算 8000"
python -m demo2_travel.main --interactive
```

If `make` is available:

```bash
make demo
```

## Environment

Set these variables in the shell or in the repo-local `.env`:

```env
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-pro
```

## Validation

```powershell
python -m demo2_travel.verify --scenario 1
python -m demo2_travel.verify --scenario 2
python -m demo2_travel.verify --scenario 3
python -m demo2_travel.verify
```

Scenario 1 uses: `2026年6月1日想去东京玩一周，预算1.5万`. The verifier injects a first-call `search_flights` no-availability result to validate replanning.

Validation writes:

- `demo2_travel/trace.md`
- `demo2_travel/data/traces/*.json`
- `demo2_travel/data/verification_report.md`

## Architecture Notes

- Planner temperature defaults to `0.7`.
- Executor temperature defaults to `0.3`.
- Planner only collects four required user constraints before planning: origin, destination, travel time window/duration, and budget.
- Every observation goes back to Planner.
- Replans that change date, destination, budget, duration, or travel class require user confirmation.
- The Executor is not allowed to alter the plan or produce final travel advice.
- Scenario fault injection is tool-call based, not user-text based.
