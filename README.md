# Hermes Agent Demos

This repository contains Hermes-native agent demos.

## Included

- `demo1_ops/`
- `demo2_travel/`
- `demo3_rag/`
- `hermes_native/`

## Run

```powershell
python -m demo1_ops.main --scenario 1
python -m demo1_ops.verify
python -m demo2_travel.main --scenario 1
python -m demo2_travel.verify
python -m demo3_rag.ingest
python -m demo3_rag.main --scenario single_001
python -m demo3_rag.viewer_server
python -m demo3_rag.verify
```

If `make` is available:

```bash
make demo
```

See `demo1_ops/README.md`, `demo2_travel/README.md`, and `demo3_rag/README.md` for full scenario and environment details.
