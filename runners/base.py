from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class RunResult:
    stdout: str
    stderr: str
    exit_code: int
    elapsed_ms: int
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None


class Runner:
    def run(self, prompt: str, workdir: str, meta: Dict) -> RunResult:
        raise NotImplementedError
