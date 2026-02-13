from __future__ import annotations

import json
import os
import re
import subprocess
import time
from typing import Any, Optional

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


def _compact_text(value: Any, limit: int = 220) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=True)
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _iter_jsonl_records(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            # Ignore non-JSONL/noisy lines by design.
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def _extract_from_jsonl(records: list[dict[str, Any]]) -> tuple[str, list[str], list[str], list[str], Optional[int], Optional[int], Optional[int], Optional[int]]:
    assistant_messages: list[str] = []
    tool_intents: list[str] = []
    tool_results: list[str] = []

    input_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

    for obj in records:
        typ = str(obj.get("type", "")).strip().lower()
        if typ == "assistant":
            content = obj.get("content")
            msg = _compact_text(content, limit=360)
            if msg:
                assistant_messages.append(msg)
        elif typ in ("tool_call", "tool_intent", "tool_use"):
            meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
            tool_name = meta.get("tool") or obj.get("tool") or obj.get("name") or typ
            args = meta.get("args") or obj.get("input") or obj.get("arguments")
            if args is not None:
                tool_intents.append(f"{_compact_text(tool_name, 80)}: {_compact_text(args, 180)}")
            else:
                tool_intents.append(_compact_text(tool_name, 120))
        elif typ == "tool_result":
            meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
            tool_name = meta.get("tool") or obj.get("tool") or "unknown"
            server = meta.get("server")
            success = meta.get("success")
            duration_ms = meta.get("duration_ms")
            parts = [f"tool={_compact_text(tool_name, 80)}"]
            if server is not None:
                parts.append(f"server={_compact_text(server, 80)}")
            if success is not None:
                parts.append(f"success={success}")
            if duration_ms is not None:
                parts.append(f"duration_ms={duration_ms}")
            tool_results.append(", ".join(parts))
        elif typ == "cost":
            meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
            raw_in = meta.get("input_tokens")
            raw_out = meta.get("output_tokens")
            raw_cached = meta.get("cached_tokens")
            raw_total = meta.get("session_tokens")
            try:
                if raw_in is not None:
                    input_tokens = int(raw_in)
                if raw_out is not None:
                    output_tokens = int(raw_out)
                if raw_cached is not None:
                    cached_tokens = int(raw_cached)
                if raw_total is not None:
                    total_tokens = int(raw_total)
            except Exception:
                pass

    # Canonical total tokens should include cached when known.
    if input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens + (cached_tokens or 0)

    final_text = assistant_messages[-1] if assistant_messages else ""
    return (
        final_text,
        assistant_messages[-12:],
        tool_intents[-24:],
        tool_results[-24:],
        input_tokens,
        cached_tokens,
        output_tokens,
        total_tokens,
    )


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
            "--mode",
            "jsonl",
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

        combined = (main.stdout or "") + "\n" + (main.stderr or "")
        records = _iter_jsonl_records(combined)
        (
            final_text,
            assistant_messages,
            tool_intents,
            tool_results,
            input_tokens,
            cached_input_tokens,
            output_tokens,
            total_tokens,
        ) = _extract_from_jsonl(records)

        if not final_text:
            # Fallback to legacy text extraction for non-jsonl output variants.
            final_text = _clean(main.stdout or "").strip()

        return ProviderRunResult(
            stdout=final_text,
            stderr=(main.stderr or "").strip(),
            exit_code=main.returncode,
            elapsed_ms=elapsed_ms,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=None,
            total_tokens=total_tokens,
            provider_trace={
                "assistant_messages": assistant_messages,
                "tool_intents": tool_intents,
                "tool_results": tool_results,
            },
        )

    def build_provider_evidence(self, run_result: ProviderRunResult) -> str:
        trace = run_result.provider_trace or {}
        assistant_messages = trace.get("assistant_messages") or []
        tool_intents = trace.get("tool_intents") or []
        tool_results = trace.get("tool_results") or []

        lines: list[str] = []
        lines.append("PROVIDER_EVIDENCE")
        lines.append("provider: octomind")
        lines.append("assistant_messages:")
        if assistant_messages:
            for msg in assistant_messages:
                lines.append(f"- {msg}")
        else:
            lines.append("- <none>")
        lines.append("tool_intents:")
        if tool_intents:
            for intent in tool_intents:
                lines.append(f"- {intent}")
        else:
            lines.append("- <none>")
        lines.append("tool_results:")
        if tool_results:
            for result in tool_results:
                lines.append(f"- {result}")
        else:
            lines.append("- <none>")
        return "\n".join(lines)
