"""Shared helpers for the harness tests."""

from __future__ import annotations

from pathlib import Path

from orderbench.evaluate import find_repo_root
from orderbench.tasks import Task, load_all

REPO = find_repo_root(Path(__file__))


def all_tasks() -> list[Task]:
    return load_all(REPO / "tasks")


def task_by_id(task_id: str) -> Task:
    return next(t for t in all_tasks() if t.id == task_id)
