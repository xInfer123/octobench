from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Optional

from providers.base import Provider, ProviderRunResult


ANSI_ESCAPE_RE = re.compile(r"\x1B[@-_][0-?]*[ -/]*[@-~]")


def _clean(text: str) -> str:
    text = ANSI_ESCAPE_RE.sub("", text)
    return "".join(ch for ch in text if ch in ("\n", "\t", "\r") or ord(ch) >= 32)


def _parse_compact_tokens(value: str) -> Optional[int]:
    v = value.strip().upper().replace(",", "")
    mul = 1
    if v.endswith("K"):
        mul = 1_000
        v = v[:-1]
    elif v.endswith("M"):
        mul = 1_000_000
        v = v[:-1]
    elif v.endswith("B"):
        mul = 1_000_000_000
        v = v[:-1]
    try:
        return int(float(v) * mul)
    except Exception:
        return None


def _extract_message(stdout: str) -> str:
    text = _clean(stdout)
    lines = [ln.rstrip() for ln in text.splitlines()]
    filtered = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("Starting new session:"):
            continue
        if s.startswith("✓ Resuming session:"):
            continue
        if s.startswith("Created:"):
            continue
        if s.startswith("Model:"):
            continue
        if s.startswith("Messages:"):
            continue
        if s.startswith("Tokens:"):
            continue
        if s.startswith("Cost:"):
            continue
        if s.startswith("Tip:") or s.startswith("?") or s.startswith("💡"):
            continue
        if s.startswith("──") or s.startswith("────────"):
            continue
        filtered.append(ln)
    return "\n".join(filtered).strip()


def _parse_info(stdout: str) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int], Optional[int]]:
    text = _clean(stdout)

    # Preferred detailed breakdown (new):
    # "Breakdown: 0 input, 0 output, 0 cached, 0 reasoning"
    # Backward-compatible (old):
    # "Breakdown: 2.1K processed, 15 output, 0 cached"
    input_tokens = output = cached = total = reasoning = None

    m_new = re.search(
        r"Breakdown:\s*([0-9.,KMBkmb]+)\s+input,\s*([0-9.,KMBkmb]+)\s+output,\s*([0-9.,KMBkmb]+)\s+cached,\s*([0-9.,KMBkmb]+)\s+reasoning",
        text,
    )
    if m_new:
        input_tokens = _parse_compact_tokens(m_new.group(1))
        output = _parse_compact_tokens(m_new.group(2))
        cached = _parse_compact_tokens(m_new.group(3))
        reasoning = _parse_compact_tokens(m_new.group(4))
        if input_tokens is not None and output is not None and cached is not None:
            total = input_tokens + output + cached + (reasoning or 0)

    if input_tokens is None:
        m_old = re.search(
            r"Breakdown:\s*([0-9.,KMBkmb]+)\s+processed,\s*([0-9.,KMBkmb]+)\s+output,\s*([0-9.,KMBkmb]+)\s+cached",
            text,
        )
        if m_old:
            input_tokens = _parse_compact_tokens(m_old.group(1))
            output = _parse_compact_tokens(m_old.group(2))
            cached = _parse_compact_tokens(m_old.group(3))
            if input_tokens is not None and output is not None and cached is not None:
                total = input_tokens + output + cached

    if total is None:
        mt = re.search(r"Total tokens:\s*([0-9.,KMBkmb]+)", text)
        if mt:
            total = _parse_compact_tokens(mt.group(1))

    if output is None:
        mo = re.search(r"\b([0-9.,KMBkmb]+)\s+output\b", text)
        if mo:
            output = _parse_compact_tokens(mo.group(1))

    if cached is None:
        mc = re.search(r"\b([0-9.,KMBkmb]+)\s+cached\b", text)
        if mc:
            cached = _parse_compact_tokens(mc.group(1))

    # Canonical semantics: input excludes cached.
    if input_tokens is None and total is not None and output is not None and cached is not None:
        input_tokens = max(total - output - cached, 0)

    return input_tokens, cached, output, reasoning, total


class OctomindProvider(Provider):
    name = "octomind"

    def __init__(self, config_path: str):
        self.config_path = config_path

    def run_task(
        self,
        prompt: str,
        workdir: str,
        provider_model: str,
        session_name: str,
    ) -> ProviderRunResult:
        env = os.environ.copy()
        env["OCTOMIND_CONFIG_PATH"] = self.config_path

        main_cmd = [
            "octomind",
            "run",
            "--name",
            session_name,
            "--role",
            "developer",
            "--model",
            provider_model,
            prompt,
        ]

        start = time.time()
        main = subprocess.run(
            main_cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            env=env,
        )
        elapsed_ms = int((time.time() - start) * 1000)

        # Query info from same session for usage/cost metrics.
        info_cmd = [
            "octomind",
            "run",
            "--resume",
            session_name,
            "/info",
        ]
        info = subprocess.run(
            info_cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            env=env,
        )

        input_tokens, cached_input_tokens, output_tokens, reasoning_tokens, total_tokens = _parse_info(
            (info.stdout or "") + "\n" + (info.stderr or "")
        )

        return ProviderRunResult(
            stdout=_extract_message(main.stdout or ""),
            stderr=(main.stderr or "").strip(),
            exit_code=main.returncode,
            elapsed_ms=elapsed_ms,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
        )
