# octobench

Benchmark framework to compare **LLM tool + config + prompt** setups across a shared set of cases.

## Key ideas
- **Cases** define prompts and scripts.
- **Providers** are Python implementations that run tools and return normalized telemetry.
- **Judge** is an LLM prompt with strict JSON output.
- **setup.sh / quality.sh / validate.sh** are bash scripts whose logs are fed to the judge.

## Quick start
1. Create a venv and install deps:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run all cases with all providers:

```bash
octobench run --cases cases --providers codex,octomind --verbosity normal
```

Results land in `results/` as JSON.

## Cases
Each case is a folder with a `case.yaml` plus optional scripts:

```
cases/edit/simple/hello/
  case.yaml
  setup.sh
  quality.sh
  validate.sh
  fixtures/
```

Script behavior:
- `setup.sh`: setup workspace/fixtures (always runs).
- `quality.sh`: run checks (lint/tests). Output is fed to the judge.
- `validate.sh`: run correctness checks. Output is fed to the judge. Any non-zero exit hard-fails the case.

Scripts run in the workspace. Use `$CASE_DIR` to access case assets (e.g., `$CASE_DIR/fixtures`).

## Providers
Provider implementations live in:
- `providers/codex.py`
- `providers/octomind.py`
- `providers/base.py`
- `providers/factory.py`

Model registry:
- `configs/models.yaml` defines benchmark model keys, pricing (per-1M), and provider-specific mappings.
- Run with all registry models by default, or filter with `--models`.

## Add new provider
1. Add provider implementation in `providers/<name>.py` implementing `Provider`.
2. Register it in `providers/factory.py`.
3. Add provider mapping under each benchmark model in `configs/models.yaml`.

## Add new benchmark model
1. Add a new key under `configs/models.yaml`.
2. Add `pricing` (per-1M input/cached_input/output).
3. Add `providers` mapping entries for each provider you use.

## Judge
The judge prompt is hardcoded in `judges/prompts.py` and expects JSON output.
Judge execution is hardcoded to Octomind with:
- `OCTOMIND_CONFIG_PATH={repo_root}/configs/octomind/octomind.toml`
- Octomind role: `judge`

## Scoring
Scoring is globally configurable via config files. The framework collects:
- judge score (0-100)
- latency
- token usage (if the CLI emits it and you configure regex)
- cost (from `configs/models.yaml`, required)
- script logs (setup/quality/validate)

Final score is computed using global scoring weights.
Validation failures hard-fail.

## Verbosity
- `--verbosity quiet`: only final output line
- `--verbosity normal`: progress per case/provider
- `--verbosity debug`: includes provider/benchmark model mapping details
