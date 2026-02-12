# Usage

## Quick run (no install)
```bash
python3 -m cli.main run --cases cases --providers codex,octomind --verbosity normal
```

This writes a JSON report under `results/<timestamp>/results.json`.

## Install CLI (recommended)
```bash
python3 -m pip install -e .
```

Then run:
```bash
octobench run --cases cases --providers codex,octomind --verbosity normal
```

Run only selected benchmark models:
```bash
octobench run --cases cases --providers codex,octomind --models gpt-5.2-codex --verbosity normal
```

Verbosity levels:
- `--verbosity quiet`
- `--verbosity normal`
- `--verbosity debug`

## What happens in a run
For each case, provider, and benchmark model:
1. Creates an isolated workspace.
2. Copies scripts to workspace.
3. Runs `setup.sh` (responsible for full setup).
4. Captures a baseline snapshot for evidence.
5. Sends the case prompt to the selected provider implementation.
6. Captures a post-run snapshot + diff evidence.
7. Runs `quality.sh` and `validate.sh`.
8. Sends tool output + script logs + evidence to the judge.
9. Computes scores and writes JSON.

## Octomind integration
- Provider implementation: `providers/octomind.py` (role: `developer`)
- Judge is hardcoded to Octomind role `judge`
- Octomind config path is passed via env:
  - `OCTOMIND_CONFIG_PATH={repo_root}/configs/octomind/octomind.toml`

## Key outputs
Each result record contains:
- tool output, logs, exit code, latency
- token usage (if configured)
- cost (from `configs/models.yaml`, per-1M tokens, required)
- judge output (score + issues)
- scoring (final score, efficiency, validation failure)
