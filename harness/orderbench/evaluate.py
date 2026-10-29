"""Workspace construction and the evaluate pipeline."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from orderbench import tamper
from orderbench.patching import PatchError, apply_patch, parse_patch
from orderbench.runner import Backend, RunResult
from orderbench.tasks import Task

# What a checkout of the environment contains. Everything else in the repo (harness, tasks,
# docs) stays on the host and is never visible to the agent or the tests.
CHECKOUT_ITEMS = ("app", "tests", "pytest.ini")
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.db", ".pytest_cache", "held_out")


def find_repo_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "tasks").is_dir() and (candidate / "app").is_dir():
            return candidate
    raise RuntimeError("could not locate the OrderBench repository root")


def clean_checkout(repo_root: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in CHECKOUT_ITEMS:
        src = repo_root / item
        if src.is_dir():
            shutil.copytree(src, dest / item, ignore=_IGNORE)
        else:
            shutil.copy2(src, dest / item)


def broken_checkout(repo_root: Path, task: Task, dest: Path) -> None:
    clean_checkout(repo_root, dest)
    apply_patch(dest, parse_patch(task.break_patch.read_text(encoding="utf-8")))


def install_held_out(task: Task, workspace: Path) -> None:
    target = workspace / task.held_out_prefix
    target.mkdir(parents=True, exist_ok=True)
    for src in sorted(task.tests_dir.glob("*.py")):
        shutil.copy2(src, target / src.name)


def _split(expected: tuple[str, ...], run: RunResult) -> dict[str, list[str]]:
    passed = sorted(n for n in expected if run.results.get(n) == "passed")
    failed = sorted(n for n in expected if n not in passed)
    return {"passed": passed, "failed": failed}


def evaluate(repo_root: Path, task: Task, patch_text: str, backend: Backend) -> dict[str, Any]:
    started = time.monotonic()
    verdict: dict[str, Any] = {
        "task_id": task.id,
        "resolved": False,
        "fail_to_pass": {"passed": [], "failed": sorted(task.fail_to_pass)},
        "pass_to_pass": {"passed": [], "failed": sorted(task.pass_to_pass)},
        "patch_applied": False,
        "timed_out": False,
        "tamper_detected": False,
        "duration_seconds": 0.0,
        "image_digest": backend.image_digest(),
    }

    def finish() -> dict[str, Any]:
        verdict["duration_seconds"] = round(time.monotonic() - started, 3)
        return verdict

    try:
        candidate = parse_patch(patch_text)
    except PatchError:
        return finish()
    if tamper.check_patch(candidate):
        verdict["tamper_detected"] = True
        return finish()

    with tempfile.TemporaryDirectory(prefix="orderbench-ws-") as tmp:
        workspace = Path(tmp) / "work"
        broken_checkout(repo_root, task, workspace)
        try:
            apply_patch(workspace, candidate)
        except PatchError:
            return finish()
        verdict["patch_applied"] = True
        install_held_out(task, workspace)
        before = tamper.snapshot(workspace)

        f2p = backend.run(workspace, list(task.fail_to_pass), task.timeout_seconds)
        p2p = backend.run(workspace, list(task.pass_to_pass), task.timeout_seconds)

        if tamper.changed_files(before, tamper.snapshot(workspace)):
            verdict["tamper_detected"] = True
            return finish()
        verdict["timed_out"] = f2p.timed_out or p2p.timed_out
        verdict["fail_to_pass"] = _split(task.fail_to_pass, f2p)
        verdict["pass_to_pass"] = _split(task.pass_to_pass, p2p)
        verdict["resolved"] = (
            not verdict["timed_out"]
            and not verdict["fail_to_pass"]["failed"]
            and not verdict["pass_to_pass"]["failed"]
        )
    return finish()


def dump_verdict(verdict: dict[str, Any]) -> str:
    return json.dumps(verdict, indent=2, sort_keys=True) + "\n"
