# Extending

## Add a new case
1. Create folder: `cases/<category>/<simple|complex>/<case_name>/`
2. Add `case.yaml` using `templates/case.yaml`.
3. Add scripts (required names):
   - `setup.sh`
   - `quality.sh`
   - `validate.sh`
4. Add fixtures in `fixtures/`.

## Add a new provider (tool)
1. Create `providers/<provider>.py` and implement `Provider.run_task(...)`.
2. Return normalized fields in `ProviderRunResult`:
   - output text, exit code, elapsed_ms
   - input/cached/output/total tokens
3. Register provider in `providers/factory.py`.

Octomind-specific:
- Provider implementation uses role `benchmark`.
- Judge remains separate and hardcoded to Octomind role `judge`.

## Add benchmark model mapping + pricing
Edit `configs/models.yaml`:
- Add benchmark model key.
- Add per-1M pricing under `pricing`.
- Add provider mappings under `providers` for each provider implementation you use.

Example:
```yaml
models:
  gpt-5.2-codex:
    pricing:
      input: 1.75
      cached_input: 0.175
      output: 14.0
    providers:
      codex: gpt-5.2-codex
      octomind: openai:gpt-5.2-codex
```

## Notes on scripts
- Scripts are bash only.
- Output is **not parsed**; it is fed to the judge.
- `validate.sh` non-zero exit = hard fail.
- Use `$CASE_DIR` inside scripts to reference case assets (e.g., `$CASE_DIR/fixtures`).
