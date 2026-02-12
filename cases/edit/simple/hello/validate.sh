#!/usr/bin/env bash
set -euo pipefail
# Hard validation: ensure greeting updated
if ! grep -q "Hello, Octobench!" hello.txt; then
  echo "VALIDATE: greeting not updated"
  exit 1
fi
