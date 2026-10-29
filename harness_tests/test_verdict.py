"""End-to-end verdict checks on the configured backend (Docker in CI)."""

from __future__ import annotations

from pathlib import Path

from orderbench.evaluate import clean_checkout, evaluate

from harness_tests.helpers import REPO, backend, task_by_id

KEYS = {
    "task_id",
    "resolved",
    "fail_to_pass",
    "pass_to_pass",
    "patch_applied",
    "timed_out",
    "tamper_detected",
    "duration_seconds",
    "image_digest",
}


def test_golden_resolves_and_empty_does_not() -> None:
    task = task_by_id("order_access_check")
    be = backend()
    golden = evaluate(REPO, task, task.golden_patch.read_text(encoding="utf-8"), be)
    empty = evaluate(REPO, task, "", be)
    assert set(golden) == KEYS
    assert golden["resolved"] is True and golden["fail_to_pass"]["failed"] == []
    assert empty["resolved"] is False and empty["fail_to_pass"]["passed"] == []
    assert golden["image_digest"] == empty["image_digest"] == be.image_digest()


def test_no_network_inside_the_sandbox(tmp_path: Path) -> None:
    """Under the harness the connection probe must actually run (not skip) and pass."""
    ws = tmp_path / "ws"
    clean_checkout(REPO, ws)
    node = "tests/test_no_network.py::test_outbound_connections_are_blocked"
    run = backend().run(ws, [node], 120)
    assert run.results == {node: "passed"}
