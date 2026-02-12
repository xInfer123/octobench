#!/usr/bin/env bash
set -euo pipefail
# Example quality check: ensure file ends with newline
python3 - <<'PY'
import pathlib, sys
p = pathlib.Path('hello.txt')
if not p.exists():
    print('QUALITY: hello.txt missing')
    sys.exit(0)
text = p.read_text()
if not text.endswith('\n'):
    print('QUALITY: hello.txt missing trailing newline')
PY
