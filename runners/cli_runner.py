from __future__ import annotations

import os
import json
import re
import subprocess
import time
from typing import Dict, Optional

from .base import RunResult


def _extract_tokens(text: str, regex: Optional[str]) -> Optional[int]:
    if not regex:
        return None
    m = re.search(regex, text)
    if not m:
        return None
    try:
        value = m.group(1)
        value = value.replace(",", "").replace("_", "")
        return int(value)
    except Exception:
        return None


def run_cli(prompt: str, workdir: str, meta: Dict) -> RunResult:
    command = meta.get("command")
    if not command:
        raise ValueError("setup missing command")

    # Write prompt to temp file for CLI tools that accept file input
    io_dir = os.path.abspath(meta.get("io_dir", workdir))
    os.makedirs(io_dir, exist_ok=True)
    io_tag = str(meta.get("io_tag", time.time_ns()))
    prompt_file = os.path.join(io_dir, f"_prompt_{io_tag}.txt")
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(prompt)
    output_file = os.path.join(io_dir, f"_output_{io_tag}.txt")

    repo_root = os.path.abspath(meta.get("repo_root", os.getcwd()))

    def _subst(arg: str) -> str:
        return (
            arg.replace("{prompt_file}", prompt_file)
            .replace("{output_file}", output_file)
            .replace("{workdir}", workdir)
            .replace("{repo_root}", repo_root)
            .replace("{provider_model}", str(meta.get("provider_model", "")))
            .replace("{benchmark_model}", str(meta.get("benchmark_model", "")))
            .replace("{prompt}", prompt)
        )

    cmd = [_subst(a) for a in command]

    start = time.time()
    stdin_prompt = meta.get("stdin_prompt", False)
    env = {**os.environ, **meta.get("env", {})}
    env = {k: _subst(v) if isinstance(v, str) else v for k, v in env.items()}

    proc = subprocess.run(
        cmd,
        cwd=workdir,
        capture_output=True,
        text=True,
        input=prompt if stdin_prompt else None,
        env=env,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    # If tool writes the final message to output_file, prefer that.
    stdout = ""
    if os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                stdout = f.read()
        except Exception:
            stdout = proc.stdout or ""
    else:
        stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    input_tokens = None
    output_tokens = None
    total_tokens = None
    cached_input_tokens = None
    last_agent_message = None

    # If tool emits JSONL events, parse usage from stdout
    if meta.get("json_events"):
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            usage = obj.get("usage")
            if isinstance(usage, dict):
                input_tokens = usage.get("input_tokens", input_tokens)
                cached_input_tokens = usage.get("cached_input_tokens", cached_input_tokens)
                output_tokens = usage.get("output_tokens", output_tokens)
                if input_tokens is not None and output_tokens is not None:
                    total_tokens = input_tokens + output_tokens
            item = obj.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                last_agent_message = item.get("text", last_agent_message)
        if last_agent_message:
            stdout = last_agent_message

    token_regexes = meta.get("token_regexes", {})
    combined = stdout + "\n" + stderr + "\n" + (proc.stdout or "")
    if input_tokens is None:
        input_tokens = _extract_tokens(combined, token_regexes.get("input"))
    if output_tokens is None:
        output_tokens = _extract_tokens(combined, token_regexes.get("output"))
    if total_tokens is None:
        total_tokens = _extract_tokens(combined, token_regexes.get("total"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    return RunResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=proc.returncode,
        elapsed_ms=elapsed_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_input_tokens,
    )
