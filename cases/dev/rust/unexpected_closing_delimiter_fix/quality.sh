#!/usr/bin/env bash
set -euo pipefail

cd octolib
cargo check --all-targets
