# Hermes Agent Demos

This repository contains Hermes-native agent demos.

## Included

- `demo1_ops/`
- `demo2_travel/`
- `hermes_native/`

## Run

```powershell
python -m demo1_ops.main --scenario 1
python -m demo1_ops.verify
python -m demo2_travel.main --scenario 1
python -m demo2_travel.verify
```

If `make` is available:

```bash
make demo
```

See `demo1_ops/README.md` and `demo2_travel/README.md` for full scenario and environment details.
