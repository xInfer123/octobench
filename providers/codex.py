from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
from typing import Optional

from providers.base import Provider, ProviderRunResult


class CodexProvider(Provider):
    name = "codex"

    def _resolve_task_dir(self, workdir: str) -> str:
        root = Path(workdir)
        if (root / ".git").exists():
            return str(root)

        git_children = []
        for child in root.iterdir():
            if child.is_dir() and (child / ".git").exists():
                git_children.append(child)

        if len(git_children) == 1:
            return str(git_children[0])
        return str(root)

    def run_task(
        self,
        prompt: str,
        workdir: str,
        provider_model: str,
        session_name: str,
    ) -> ProviderRunResult:
        task_dir = self._resolve_task_dir(workdir)
        output_file = os.path.join(workdir, f"_provider_output_{session_name}.txt")
        cmd = [
            "codex",
            "exec",
            "--json",
            "-m",
            provider_model,
            "-C",
            task_dir,
            "-s",
            "workspace-write",
            "--skip-git-repo-check",
            "--output-last-message",
            output_file,
            "-",
        ]

        start = time.time()
        proc = subprocess.run(
            cmd,
            cwd=task_dir,
            capture_output=True,
            text=True,
            input=prompt,
            env=os.environ.copy(),
        )
        elapsed_ms = int((time.time() - start) * 1000)

        stdout = ""
        if os.path.exists(output_file):
            try:
                with open(output_file, "r", encoding="utf-8") as f:
                    stdout = f.read().strip()
            except Exception:
                stdout = (proc.stdout or "").strip()
        else:
            stdout = (proc.stdout or "").strip()

        input_tokens: Optional[int] = None
        cached_input_tokens: Optional[int] = None
        output_tokens: Optional[int] = None
        total_tokens: Optional[int] = None

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
                raw_input_tokens = usage.get("input_tokens")
                if raw_input_tokens is not None:
                    input_tokens = raw_input_tokens
                cached_input_tokens = usage.get("cached_input_tokens", cached_input_tokens)
                output_tokens = usage.get("output_tokens", output_tokens)
                # Normalize to canonical semantics where input excludes cached.
                if input_tokens is not None and cached_input_tokens is not None:
                    input_tokens = max(input_tokens - cached_input_tokens, 0)
                if input_tokens is not None and output_tokens is not None:
                    total_tokens = input_tokens + (cached_input_tokens or 0) + output_tokens
            item = obj.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    stdout = text.strip()

        return ProviderRunResult(
            stdout=stdout,
            stderr=(proc.stderr or "").strip(),
            exit_code=proc.returncode,
            elapsed_ms=elapsed_ms,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=None,
            total_tokens=total_tokens,
        )
