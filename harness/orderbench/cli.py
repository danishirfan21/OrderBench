"""Command line interface: list, prepare, evaluate, validate-all."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from orderbench.evaluate import broken_checkout, dump_verdict, evaluate, find_repo_root
from orderbench.patching import PatchError
from orderbench.runner import select_backend
from orderbench.tasks import Task, TaskError, load_all
from orderbench.validate import TaskReport, validate_task


def _tasks(repo_root: Path) -> list[Task]:
    return load_all(repo_root / "tasks")


def _find(tasks: list[Task], task_id: str) -> Task:
    for task in tasks:
        if task.id == task_id:
            return task
    raise SystemExit(f"unknown task {task_id!r}; run `orderbench list`")


def cmd_list(args: argparse.Namespace) -> int:
    tasks = _tasks(find_repo_root())
    print(f"{'ID':<34} {'DIFFICULTY':<10} {'TRAP':<5} TITLE")
    for t in tasks:
        print(f"{t.id:<34} {t.difficulty:<10} {'yes' if t.trap else 'no':<5} {t.title}")
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    repo_root = find_repo_root()
    task = _find(_tasks(repo_root), args.task)
    out = Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} exists and is not empty")
    broken_checkout(repo_root, task, out)
    (out / "TASK.md").write_text(
        f"# {task.title}\n\n{task.statement}\n\n---\nRun the visible suite with "
        "`python -m pytest -c pytest.ini tests`. Submit your fix as a unified diff "
        "(`git diff`) touching only Python modules under `app/`.\n",
        encoding="utf-8",
    )
    if shutil.which("git"):
        git = ["git", "-c", "user.name=orderbench", "-c", "user.email=orderbench@localhost"]
        for step in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "broken baseline"]):
            subprocess.run([*git, *step], cwd=out, check=False, capture_output=True)
    print(f"prepared {task.id} in {out}")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    repo_root = find_repo_root()
    task = _find(_tasks(repo_root), args.task)
    patch_text = (
        Path(args.patch).read_text(encoding="utf-8") if args.patch != "-" else sys.stdin.read()
    )
    backend = select_backend(repo_root, args.backend)
    verdict = evaluate(repo_root, task, patch_text, backend)
    if args.json:
        sys.stdout.write(dump_verdict(verdict))
    else:
        f2p, p2p = verdict["fail_to_pass"], verdict["pass_to_pass"]
        print(f"task        {verdict['task_id']}")
        print(f"resolved    {verdict['resolved']}")
        print(f"fail_to_pass {len(f2p['passed'])} passed / {len(f2p['failed'])} failed")
        print(f"pass_to_pass {len(p2p['passed'])} passed / {len(p2p['failed'])} failed")
        print(
            f"patch_applied={verdict['patch_applied']} timed_out={verdict['timed_out']} "
            f"tamper_detected={verdict['tamper_detected']} ({verdict['duration_seconds']}s)"
        )
    return 0 if verdict["resolved"] else 1


def cmd_validate_all(args: argparse.Namespace) -> int:
    repo_root = find_repo_root()
    try:
        tasks = _tasks(repo_root)
    except TaskError as exc:
        print(f"FAIL task schema: {exc}")
        return 1
    backend = select_backend(repo_root, args.backend)
    failures = 0
    for task in tasks:
        try:
            report = validate_task(repo_root, task, backend)
        except PatchError as exc:
            report = TaskReport(task.id, problems=[f"patch does not apply: {exc}"])
        status = "ok  " if report.ok else "FAIL"
        trap = " [trap]" if task.trap else ""
        print(f"{status} {task.id} ({task.difficulty}){trap}", flush=True)
        for problem in report.problems:
            print(f"       - {problem}", flush=True)
        failures += 0 if report.ok else 1
    print(f"{len(tasks) - failures}/{len(tasks)} tasks valid")
    return 0 if failures == 0 and tasks else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orderbench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list tasks").set_defaults(func=cmd_list)

    p = sub.add_parser("prepare", help="write a broken checkout plus TASK.md for an agent")
    p.add_argument("--task", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("evaluate", help="score a candidate patch")
    p.add_argument("--task", required=True)
    p.add_argument("--patch", required=True, help="path to a unified diff, or - for stdin")
    p.add_argument("--json", action="store_true", help="print the JSON verdict")
    p.add_argument("--backend", choices=["auto", "docker", "local"])
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("validate-all", help="check every task's broken/golden/trap behaviour")
    p.add_argument("--backend", choices=["auto", "docker", "local"])
    p.set_defaults(func=cmd_validate_all)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
