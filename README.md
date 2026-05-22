# Hermes Agent Demos

This repository contains Hermes-native agent demos.

## Included

- `demo1_ops/`
- `demo2_travel/`
- `demo3_rag/`
- `demo4_blackboard/`
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
conda run -n hermes-demos python -m demo4_blackboard.main --topic "retrieval augmented generation evaluation methods"
conda run -n hermes-demos python replay.py --topic "retrieval augmented generation evaluation methods"
```

If `make` is available:

```bash
make demo
```

See `demo1_ops/README.md`, `demo2_travel/README.md`, and `demo3_rag/README.md` for full scenario and environment details.
See `demo4_blackboard/README.md` for the multi-agent blackboard arXiv review demo.
