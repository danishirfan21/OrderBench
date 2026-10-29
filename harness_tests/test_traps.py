"""Each trap's shallow fix must satisfy fail_to_pass yet be rejected by pass_to_pass."""

from __future__ import annotations

import pytest
from orderbench.evaluate import evaluate

from harness_tests.helpers import REPO, all_tasks, backend

TRAPPED = [t for t in all_tasks() if t.trap is not None]


@pytest.mark.parametrize("task", TRAPPED, ids=lambda t: t.id)
def test_shallow_fix_passes_f2p_but_fails_p2p(task) -> None:  # type: ignore[no-untyped-def]
    assert task.trap is not None
    patch = (task.directory / task.trap.shallow_patch).read_text(encoding="utf-8")
    verdict = evaluate(REPO, task, patch, backend())
    assert verdict["patch_applied"] and not verdict["tamper_detected"]
    assert verdict["fail_to_pass"]["failed"] == []
    assert verdict["pass_to_pass"]["failed"] != []
    assert verdict["resolved"] is False
