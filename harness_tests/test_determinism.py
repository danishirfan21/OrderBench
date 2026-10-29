"""Two identical evaluate runs must produce byte-identical verdicts (except the duration)."""

from __future__ import annotations

import json

from orderbench.evaluate import dump_verdict, evaluate
from orderbench.runner import LocalBackend

from harness_tests.helpers import REPO, task_by_id


def _stable(verdict: dict[str, object]) -> str:
    return dump_verdict({**verdict, "duration_seconds": 0})


def test_identical_runs_give_identical_verdicts() -> None:
    task = task_by_id("pagination_offset")
    golden = task.golden_patch.read_text(encoding="utf-8")
    first = evaluate(REPO, task, golden, LocalBackend())
    second = evaluate(REPO, task, golden, LocalBackend())
    assert first["resolved"] is True
    assert _stable(first) == _stable(second)
    assert _stable(first).encode() == _stable(second).encode()
    assert json.loads(_stable(first))["task_id"] == "pagination_offset"


def test_failing_verdicts_are_deterministic_too() -> None:
    task = task_by_id("stale_stock_reservation")
    first = evaluate(REPO, task, "", LocalBackend())
    second = evaluate(REPO, task, "", LocalBackend())
    assert first["resolved"] is False
    assert _stable(first) == _stable(second)
