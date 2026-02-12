#!/usr/bin/env bash
set -euo pipefail
if grep -q "process_data" app.py cli.py; then
  echo "VALIDATE: old name still present"
  exit 1
fi
if ! grep -q "transform_data" app.py cli.py; then
  echo "VALIDATE: new name missing"
  exit 1
fi
