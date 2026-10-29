"""Reward-integrity checks: the allowlist and the content scan."""

from __future__ import annotations

import pytest
from orderbench.evaluate import evaluate
from orderbench.patching import make_diff, parse_patch
from orderbench.tamper import check_patch

from harness_tests.helpers import REPO, backend, task_by_id


def _violations(path: str, old: str | None, new: str | None) -> list[str]:
    return [str(v) for v in check_patch(parse_patch(make_diff(path, old, new)))]


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_orders.py",
        "tests/conftest.py",
        "conftest.py",
        "app/conftest.py",
        "pytest.ini",
        "sitecustomize.py",
        "app/sitecustomize.py",
        "harness/orderbench/guard.py",
        "tasks/pagination_offset/task.yaml",
        "tests/held_out/pagination_offset/test_pagination_offset.py",
        "app/data.json",
        "pyproject.toml",
    ],
)
def test_paths_outside_the_allowlist_are_rejected(path: str) -> None:
    assert _violations(path, "a = 1\n", "a = 2\n")


def test_ordinary_app_edit_is_allowed() -> None:
    assert not _violations("app/pagination.py", "a = 1\n", "a = 2\n")


@pytest.mark.parametrize(
    "line",
    [
        "import sys; sys.modules['pytest'] = None",
        "import importlib",
        "exec('x')",
        "import atexit",
        "raise SystemExit(0) if False else sys.exit(0)",
        "import subprocess",
        "import socket",
        "from unittest import mock",
    ],
)
def test_suspicious_added_code_is_rejected(line: str) -> None:
    assert _violations("app/pagination.py", "a = 1\n", f"a = 1\n{line}\n")


def test_patch_touching_tests_is_flagged_in_the_verdict() -> None:
    task = task_by_id("pagination_offset")
    text = make_diff("tests/test_pagination.py", "x = 1\n", "x = 2\n")
    verdict = evaluate(REPO, task, text, backend())
    assert verdict["tamper_detected"] is True
    assert verdict["resolved"] is False
    assert verdict["patch_applied"] is False
