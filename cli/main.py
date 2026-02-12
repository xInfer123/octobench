from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import yaml

from judges.llm_judge import run_judge
from providers.factory import available_providers, get_provider
from scoring.aggregate import compute_cost, compute_efficiency_score, compute_final_score


def snapshot_files(workdir: Path) -> Dict[str, Dict]:
    files = {}
    for path in workdir.rglob("*"):
        if path.is_file():
            rel = str(path.relative_to(workdir))
            if rel.startswith("_provider_output_") or rel.startswith("_prompt_") or rel.startswith("_output_"):
                continue
            try:
                data = path.read_bytes()
            except Exception:
                continue
            content = None
            try:
                text = data.decode("utf-8")
                if len(text) <= 4000:
                    content = text
            except Exception:
                content = None
            files[rel] = {
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "content": content,
            }
    return files


def diff_snapshots(before: Dict[str, Dict], after: Dict[str, Dict]) -> Dict:
    before_set = set(before.keys())
    after_set = set(after.keys())
    added = sorted(after_set - before_set)
    deleted = sorted(before_set - after_set)
    modified = sorted(k for k in (before_set & after_set) if before[k]["sha256"] != after[k]["sha256"])
    return {"added": added, "deleted": deleted, "modified": modified}


def build_evidence(before: Dict[str, Dict], after: Dict[str, Dict], diff: Dict) -> str:
    lines = []
    lines.append("CHANGES")
    lines.append(f"added: {len(diff['added'])}")
    lines.append(f"deleted: {len(diff['deleted'])}")
    lines.append(f"modified: {len(diff['modified'])}")
    for label in ["added", "deleted", "modified"]:
        if diff[label]:
            lines.append(f"{label}:")
            lines.extend([f"- {p}" for p in diff[label]])

    for rel in diff["modified"]:
        before_c = before.get(rel, {}).get("content")
        after_c = after.get(rel, {}).get("content")
        if before_c is None or after_c is None:
            continue
        diff_lines = difflib.unified_diff(
            before_c.splitlines(),
            after_c.splitlines(),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            lineterm="",
        )
        lines.append("\n".join(diff_lines))

    return "\n".join(lines)


def load_yaml(path: Path) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_case_files(root: Path) -> List[Path]:
    return list(root.rglob("case.yaml"))


def run_script(script_name: str, workdir: Path, env: Dict[str, str] | None = None) -> Dict:
    script_path = workdir / script_name
    if not script_path.exists():
        return {"exit_code": 0, "stdout": "", "stderr": "", "elapsed_ms": 0}
    start = time.time()
    result = subprocess.run(
        ["bash", script_name],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    elapsed_ms = int((time.time() - start) * 1000)
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
        "elapsed_ms": elapsed_ms,
    }


def ensure_workspace(case_dir: Path, run_dir: Path) -> Path:
    workdir = run_dir / "workspace"
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    for name in ["setup.sh", "quality.sh", "validate.sh"]:
        src = case_dir / name
        if src.exists():
            shutil.copy2(src, workdir / name)
    return workdir


def build_task_prompt(case: Dict) -> str:
    return f"System:\n{case.get('system_prompt', '')}\n\nInstruction:\n{case.get('instruction', '')}\n"


def parse_selected_models(models_cfg: Dict, models_arg: str | None) -> List[str]:
    available = list(models_cfg.get("models", {}).keys())
    if not models_arg:
        return available
    selected = [m.strip() for m in models_arg.split(",") if m.strip()]
    unknown = [m for m in selected if m not in models_cfg.get("models", {})]
    if unknown:
        raise RuntimeError(f"Unknown benchmark model(s): {', '.join(unknown)}")
    return selected


def resolve_provider_model(models_cfg: Dict, benchmark_model: str, provider: str) -> str:
    entry = models_cfg.get("models", {}).get(benchmark_model, {})
    providers = entry.get("providers", {})
    mapped = providers.get(provider)
    if mapped is None:
        raise RuntimeError(
            f"Missing provider mapping for benchmark_model '{benchmark_model}' and provider '{provider}'"
        )
    if isinstance(mapped, dict):
        model_id = mapped.get("id")
    else:
        model_id = mapped
    if not model_id:
        raise RuntimeError(
            f"Invalid provider mapping for benchmark_model '{benchmark_model}' and provider '{provider}'"
        )
    return str(model_id)


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def should_log(level: str, current: str) -> bool:
    rank = {"quiet": 0, "normal": 1, "debug": 2}
    return rank.get(current, 1) >= rank.get(level, 1)


def log(msg: str, verbosity: str, level: str = "normal") -> None:
    if should_log(level, verbosity):
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        print(f"[{ts}] {msg}", file=sys.stderr)


def parse_providers(arg: str | None) -> List[str]:
    all_known = set(available_providers())
    if not arg:
        return sorted(all_known)
    selected = [p.strip() for p in arg.split(",") if p.strip()]
    unknown = [p for p in selected if p not in all_known]
    if unknown:
        raise RuntimeError(f"Unknown provider(s): {', '.join(unknown)}")
    return selected


def default_judge_cfg(repo_root: Path) -> Dict:
    return {
        "name": "octomind_judge",
        "runner": "cli",
        "model": "openrouter:anthropic/claude-sonnet-4",
        "stdin_prompt": False,
        "command": ["octomind", "run", "--role", "judge", "{prompt}"],
        "env": {
            "OCTOMIND_CONFIG_PATH": f"{repo_root}/configs/octomind/octomind.toml",
        },
        "response_format": "json",
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="octobench")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run benchmarks")
    run_p.add_argument("--cases", required=True)
    run_p.add_argument("--providers", default="codex,octomind", help="Comma-separated providers")
    run_p.add_argument("--models", default=None, help="Comma-separated benchmark model keys")
    run_p.add_argument("--out", default="results")
    run_p.add_argument("--scoring", default="configs/scoring.yaml")
    run_p.add_argument("--efficiency", default="configs/efficiency.yaml")
    run_p.add_argument("--verbosity", choices=["quiet", "normal", "debug"], default="normal")

    args = parser.parse_args()

    if args.cmd != "run":
        return

    verbosity = args.verbosity
    repo_root = Path.cwd().resolve()
    cases_root = Path(args.cases)
    judge_cfg = default_judge_cfg(repo_root)
    models_path = repo_root / "configs" / "models.yaml"
    if not models_path.exists():
        raise RuntimeError(f"Missing required models config: {models_path}")
    models_cfg = load_yaml(models_path)
    selected_models = parse_selected_models(models_cfg, args.models)
    selected_providers = parse_providers(args.providers)

    scoring_cfg = load_yaml(Path(args.scoring)) if Path(args.scoring).exists() else {
        "judge_weight": 0.85,
        "efficiency_weight": 0.15,
    }
    efficiency_cfg = load_yaml(Path(args.efficiency)) if Path(args.efficiency).exists() else {
        "latency_ms": 8000,
        "cost_usd": 0.2,
        "tps": 50,
        "weight_latency": 0.4,
        "weight_cost": 0.4,
        "weight_tps": 0.2,
    }

    case_files = find_case_files(cases_root)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    run_root = Path(args.out) / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    all_results = []

    provider_impls = {name: get_provider(name, repo_root) for name in selected_providers}

    log(
        f"[octobench] loaded {len(selected_models)} model(s), {len(selected_providers)} provider(s), cases from {cases_root}",
        verbosity,
        "normal",
    )

    for case_file in case_files:
        case = load_yaml(case_file)
        case_dir = case_file.parent
        case_id = case.get("id", case_dir.name)
        case_run_dir = run_root / case_id
        case_run_dir.mkdir(parents=True, exist_ok=True)
        log(f"[octobench] case={case_id}", verbosity, "normal")

        for provider_name in selected_providers:
            provider_impl = provider_impls[provider_name]
            for benchmark_model in selected_models:
                provider_model = resolve_provider_model(models_cfg, benchmark_model, provider_name)
                setup_name = f"{provider_name}__{safe_id(benchmark_model)}"
                setup_run_dir = case_run_dir / setup_name
                setup_run_dir.mkdir(parents=True, exist_ok=True)

                log(
                    f"[octobench] run provider={provider_name} benchmark_model={benchmark_model} provider_model={provider_model}",
                    verbosity,
                    "debug",
                )

                workdir = ensure_workspace(case_dir, setup_run_dir)
                workdir_abs = workdir.resolve()

                env = {
                    "CASE_DIR": str(case_dir.resolve()),
                    "WORKDIR": str(workdir_abs),
                }
                setup_log = run_script("setup.sh", workdir_abs, env=env)
                if setup_log["exit_code"] != 0:
                    quality_log = run_script("quality.sh", workdir_abs, env=env)
                    validation_log = run_script("validate.sh", workdir_abs, env=env)
                    judge_payload = {
                        "task": "",
                        "model_output": "",
                        "prep_log": setup_log["stdout"] + setup_log["stderr"],
                        "quality_log": quality_log["stdout"] + quality_log["stderr"],
                        "validation_log": validation_log["stdout"] + validation_log["stderr"],
                        "evidence_log": "",
                    }
                    judge_meta = dict(judge_cfg)
                    judge_meta["io_dir"] = str(setup_run_dir.resolve())
                    judge_meta["repo_root"] = str(repo_root)
                    judge_out = run_judge(judge_payload, judge_meta, str(workdir_abs))
                    record = {
                        "case_id": case_id,
                        "setup": setup_name,
                        "provider": provider_name,
                        "model": benchmark_model,
                        "provider_model": provider_model,
                        "runner": "provider",
                        "result": {
                            "stdout": "",
                            "stderr": "setup failed",
                            "exit_code": 1,
                            "elapsed_ms": 0,
                        },
                        "tokens": {"input": None, "cached_input": None, "output": None, "reasoning": None, "total": None},
                        "cost_usd": None,
                        "scripts": {
                            "setup": setup_log,
                            "quality": quality_log,
                            "validate": validation_log,
                        },
                        "evidence": "",
                        "workdir": str(workdir_abs),
                        "judge": judge_out,
                        "scoring": {},
                    }
                    all_results.append(record)
                    continue

                prompt = build_task_prompt(case)
                before = snapshot_files(workdir_abs)

                session_name = f"octobench-{case_id}-{provider_name}-{safe_id(benchmark_model)}-{int(time.time()*1000)}"
                provider_result = provider_impl.run_task(
                    prompt=prompt,
                    workdir=str(workdir_abs),
                    provider_model=provider_model,
                    session_name=session_name,
                )

                after = snapshot_files(workdir_abs)
                diff = diff_snapshots(before, after)
                evidence_log = build_evidence(before, after, diff)

                quality_log = run_script("quality.sh", workdir_abs, env=env)
                validation_log = run_script("validate.sh", workdir_abs, env=env)

                judge_payload = {
                    "task": prompt,
                    "model_output": (provider_result.stdout or "") + (provider_result.stderr or ""),
                    "prep_log": setup_log["stdout"] + setup_log["stderr"],
                    "quality_log": quality_log["stdout"] + quality_log["stderr"],
                    "validation_log": validation_log["stdout"] + validation_log["stderr"],
                    "evidence_log": evidence_log,
                }
                judge_meta = dict(judge_cfg)
                judge_meta["io_dir"] = str(setup_run_dir.resolve())
                judge_meta["repo_root"] = str(repo_root)
                judge_out = run_judge(judge_payload, judge_meta, str(workdir_abs))

                pricing = models_cfg.get("models", {}).get(benchmark_model, {}).get("pricing")
                if not pricing:
                    raise RuntimeError(f"Missing pricing for benchmark model: {benchmark_model}")

                eval_cost = compute_cost(
                    provider_result.input_tokens,
                    provider_result.cached_input_tokens,
                    provider_result.output_tokens,
                    pricing,
                )

                record = {
                    "case_id": case_id,
                    "setup": setup_name,
                    "provider": provider_name,
                    "model": benchmark_model,
                    "provider_model": provider_model,
                    "runner": "provider",
                    "result": {
                        "stdout": provider_result.stdout,
                        "stderr": provider_result.stderr,
                        "exit_code": provider_result.exit_code,
                        "elapsed_ms": provider_result.elapsed_ms,
                    },
                    "tokens": {
                        "input": provider_result.input_tokens,
                        "cached_input": provider_result.cached_input_tokens,
                        "output": provider_result.output_tokens,
                        "reasoning": provider_result.reasoning_tokens,
                        "total": provider_result.total_tokens,
                    },
                    "cost_usd": eval_cost,
                    "scripts": {
                        "setup": setup_log,
                        "quality": quality_log,
                        "validate": validation_log,
                    },
                    "evidence": evidence_log,
                    "workdir": str(workdir_abs),
                    "judge": judge_out,
                    "scoring": {},
                }
                all_results.append(record)
                log(
                    f"[octobench] completed case={case_id} setup={setup_name} exit={provider_result.exit_code}",
                    verbosity,
                    "normal",
                )

    for case_id in {r["case_id"] for r in all_results}:
        case_rows = [r for r in all_results if r["case_id"] == case_id]
        for r in case_rows:
            judge_score = float(r["judge"].get("score", 0))
            efficiency = compute_efficiency_score(
                r["result"]["elapsed_ms"], r["tokens"]["total"], r.get("cost_usd"), efficiency_cfg
            )
            validation_failed = r["scripts"]["validate"]["exit_code"] != 0
            final_score = 0.0 if validation_failed else compute_final_score(judge_score, efficiency, scoring_cfg)
            r["scoring"].update(
                {
                    "efficiency_score": efficiency,
                    "final_score": final_score,
                    "validation_failed": validation_failed,
                    "judge_weight": scoring_cfg.get("judge_weight", 0.85),
                    "efficiency_weight": scoring_cfg.get("efficiency_weight", 0.15),
                }
            )

    out_path = run_root / "results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"results": all_results}, f, indent=2)

    log(f"[octobench] wrote results to {out_path}", verbosity, "normal")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
