"""``validate-all``: the repository's own test of its tasks."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from orderbench.evaluate import broken_checkout, evaluate
from orderbench.runner import Backend
from orderbench.tasks import Task


@dataclass
class TaskReport:
    task_id: str
    problems: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def validate_task(repo_root: Path, task: Task, backend: Backend) -> TaskReport:
    report = TaskReport(task.id)

    def expect(condition: bool, label: str, detail: str = "") -> None:
        if condition:
            report.checks.append(label)
        else:
            report.problems.append(f"{label}{': ' + detail if detail else ''}")

    # 1. Broken state (empty candidate patch): fail_to_pass fail, pass_to_pass hold, not resolved.
    broken = evaluate(repo_root, task, "", backend)
    expect(broken["patch_applied"], "empty patch applies")
    expect(
        not broken["fail_to_pass"]["passed"],
        "broken state fails every fail_to_pass test",
        f"unexpectedly passing: {broken['fail_to_pass']['passed']}",
    )
    expect(
        not broken["pass_to_pass"]["failed"],
        "pass_to_pass holds in the broken state",
        f"failing: {broken['pass_to_pass']['failed']}",
    )
    expect(not broken["resolved"], "empty patch does not resolve")

    # 2. Golden patch resolves.
    golden = evaluate(repo_root, task, task.golden_patch.read_text(encoding="utf-8"), backend)
    expect(
        golden["patch_applied"] and not golden["tamper_detected"], "golden patch applies cleanly"
    )
    expect(
        not golden["fail_to_pass"]["failed"],
        "golden patch makes fail_to_pass pass",
        f"failing: {golden['fail_to_pass']['failed']}",
    )
    expect(
        not golden["pass_to_pass"]["failed"],
        "pass_to_pass holds after the golden patch",
        f"failing: {golden['pass_to_pass']['failed']}",
    )
    expect(golden["resolved"], "golden patch resolves")

    # 3. The visible suite never reveals the bug: the whole base suite is green on the broken tree.
    with tempfile.TemporaryDirectory(prefix="orderbench-leak-") as tmp:
        ws = Path(tmp) / "work"
        broken_checkout(repo_root, task, ws)
        run = backend.run(ws, ["tests"], 600)
        bad = sorted(n for n, o in run.results.items() if o != "passed")
        expect(
            bool(run.results) and not bad, "visible suite is green on the broken tree", str(bad[:5])
        )

    # 4. Trap: the shallow fix passes fail_to_pass but is caught by pass_to_pass.
    if task.trap is not None:
        shallow = evaluate(
            repo_root,
            task,
            (task.directory / task.trap.shallow_patch).read_text(encoding="utf-8"),
            backend,
        )
        expect(shallow["patch_applied"], "trap patch applies")
        expect(
            not shallow["fail_to_pass"]["failed"],
            "trap patch passes every fail_to_pass test",
            f"failing: {shallow['fail_to_pass']['failed']}",
        )
        expect(
            bool(shallow["pass_to_pass"]["failed"]) and not shallow["resolved"],
            "trap patch is caught by pass_to_pass",
        )
    return report
