from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProviderRunResult:
    stdout: str
    stderr: str
    exit_code: int
    elapsed_ms: int
    input_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class Provider(ABC):
    name: str

    @abstractmethod
    def run_task(
        self,
        prompt: str,
        workdir: str,
        provider_model: str,
        session_name: str,
    ) -> ProviderRunResult:
        raise NotImplementedError
