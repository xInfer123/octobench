#!/usr/bin/env bash
set -euo pipefail

cd octolib

MINIMAX_FILE="$(rg --files | rg 'minimax\.rs$' | head -n 1)"
if [[ -z "${MINIMAX_FILE}" ]]; then
  echo "validate: minimax.rs not found"
  exit 1
fi

EXPECT_FILE=".bench_expectations/minimax_models.txt"
if [[ ! -f "${EXPECT_FILE}" ]]; then
  echo "validate: expectation file missing (${EXPECT_FILE})"
  exit 1
fi

echo "[validate] checking build"
cargo check --all-targets

echo "[validate] checking minimax model coverage"
missing=0
while IFS= read -r model; do
  [[ -z "${model}" ]] && continue
  if ! grep -Fq "${model}" "${MINIMAX_FILE}"; then
    echo "missing minimax model string: ${model}"
    missing=1
  fi
done < "${EXPECT_FILE}"

if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

echo "[validate] checking scaffold removal"
if grep -Fq "Feature scaffold inserted by benchmark setup" "${MINIMAX_FILE}"; then
  echo "feature scaffold marker still present"
  exit 1
fi

echo "validate: minimax provider feature checks passed"
