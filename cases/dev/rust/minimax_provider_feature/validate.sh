#!/usr/bin/env bash
set -euo pipefail

MINIMAX_FILE="src/llm/providers/minimax.rs"
if [[ ! -f "${MINIMAX_FILE}" ]]; then
  echo "validate: expected file missing: ${MINIMAX_FILE}"
  exit 1
fi

EXPECT_FILE=".bench_expectations/minimax_models.txt"
if [[ ! -f "${EXPECT_FILE}" ]]; then
  echo "validate: expectation file missing (${EXPECT_FILE})"
  exit 1
fi

if ! cargo check --all-targets --quiet; then
  exit 1
fi

missing=0
while IFS= read -r model; do
  [[ -z "${model}" ]] && continue
  if ! grep -Fqi "${model}" "${MINIMAX_FILE}"; then
    echo "missing minimax model string: ${model}"
    missing=1
  fi
done < "${EXPECT_FILE}"

if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi
