"""Two identical evaluate runs must produce byte-identical verdicts (except the duration)."""

from __future__ import annotations

import json

from orderbench.evaluate import dump_verdict, evaluate

from harness_tests.helpers import REPO, backend, task_by_id


def _stable(verdict: dict[str, object]) -> str:
    return dump_verdict({**verdict, "duration_seconds": 0})


def test_identical_runs_give_identical_verdicts() -> None:
    task = task_by_id("pagination_offset")
    golden = task.golden_patch.read_text(encoding="utf-8")
    first = evaluate(REPO, task, golden, backend())
    second = evaluate(REPO, task, golden, backend())
    assert first["resolved"] is True
    assert _stable(first) == _stable(second)
    assert _stable(first).encode() == _stable(second).encode()
    assert json.loads(_stable(first))["task_id"] == "pagination_offset"


def test_failing_verdicts_are_deterministic_too() -> None:
    task = task_by_id("stale_stock_reservation")
    first = evaluate(REPO, task, "", backend())
    second = evaluate(REPO, task, "", backend())
    assert first["resolved"] is False
    assert _stable(first) == _stable(second)
