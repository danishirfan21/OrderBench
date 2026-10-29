"""Score an agent across every OrderBench task and print the resolve rate.

An agent is any callable ``(workspace: Path, task: Task) -> None`` that may read and edit the
files in ``workspace`` (a copy of the broken repository; ``task.statement`` is the bug report); the
patch is computed from what changed under ``app/``. Swap ``oracle_agent`` for your own function
(an LLM tool-use loop, a script, ...).

    python examples/run_agent.py                 # oracle stub: applies each golden patch
    python examples/run_agent.py --agent empty   # stub that changes nothing
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from orderbench.evaluate import broken_checkout, evaluate, find_repo_root
from orderbench.patching import apply_patch, make_diff, parse_patch
from orderbench.runner import select_backend
from orderbench.tasks import Task, load_all

Agent = Callable[[Path, Task], None]


def oracle_agent(workspace: Path, task: Task) -> None:
    """Stub that "solves" the task by writing the golden patch's result into the workspace."""
    apply_patch(workspace, parse_patch(task.golden_patch.read_text(encoding="utf-8")))


def empty_agent(workspace: Path, task: Task) -> None:
    """Stub that makes no change at all."""


AGENTS: dict[str, Agent] = {"oracle": oracle_agent, "empty": empty_agent}


def diff_app(before: Path, after: Path) -> str:
    """Unified diff of every python file under app/ between two trees."""
    parts: list[str] = []
    paths = {p.relative_to(before).as_posix() for p in (before / "app").rglob("*.py")}
    paths |= {p.relative_to(after).as_posix() for p in (after / "app").rglob("*.py")}
    for rel in sorted(paths):
        old = (before / rel).read_text(encoding="utf-8") if (before / rel).exists() else None
        new = (after / rel).read_text(encoding="utf-8") if (after / rel).exists() else None
        if old != new:
            parts.append(make_diff(rel, old, new))
    return "".join(parts)


def run_agent(agent: Agent, repo_root: Path, backend_name: str | None) -> float:
    backend = select_backend(repo_root, backend_name)
    tasks = load_all(repo_root / "tasks")
    resolved = 0
    for task in tasks:
        with tempfile.TemporaryDirectory(prefix="orderbench-agent-") as tmp:
            base, work = Path(tmp) / "base", Path(tmp) / "work"
            broken_checkout(repo_root, task, base)
            shutil.copytree(base, work)
            agent(work, task)
            patch = diff_app(base, work)
        verdict = evaluate(repo_root, task, patch, backend)
        resolved += bool(verdict["resolved"])
        print(f"{'RESOLVED' if verdict['resolved'] else 'failed  '}  {task.id} ({task.difficulty})")
    rate = resolved / len(tasks)
    print(f"\nresolve rate: {resolved}/{len(tasks)} = {rate:.1%}")
    return rate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--agent", choices=sorted(AGENTS), default="oracle")
    parser.add_argument("--backend", choices=["auto", "docker", "local"], default=None)
    args = parser.parse_args()
    run_agent(AGENTS[args.agent], find_repo_root(Path(__file__)), args.backend)
    return 0


if __name__ == "__main__":
    sys.exit(main())
