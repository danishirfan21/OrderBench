"""Schema and composition checks over tasks/."""

from __future__ import annotations

from collections import Counter

from orderbench.tasks import HELD_OUT_DIR

from harness_tests.helpers import all_tasks


def test_exactly_eight_tasks_with_required_difficulty_mix() -> None:
    tasks = all_tasks()
    assert len(tasks) == 8
    assert Counter(t.difficulty for t in tasks) == {"easy": 2, "medium": 4, "hard": 2}


def test_at_least_two_traps_and_their_patches_exist() -> None:
    trapped = [t for t in all_tasks() if t.trap is not None]
    assert len(trapped) >= 2
    for t in trapped:
        assert t.trap is not None
        assert (t.directory / t.trap.shallow_patch).is_file()
        assert t.trap.why_it_fails


def test_every_task_has_its_files_and_ids() -> None:
    for t in all_tasks():
        assert t.break_patch.is_file() and t.golden_patch.is_file()
        assert any(t.tests_dir.glob("test_*.py"))
        assert t.fail_to_pass and t.pass_to_pass
        assert all(i.startswith(f"{HELD_OUT_DIR}/{t.id}/") for i in t.fail_to_pass)
        assert not set(t.fail_to_pass) & set(t.pass_to_pass)


def test_statements_do_not_leak_the_location() -> None:
    for t in all_tasks():
        assert ".py" not in t.statement, t.id
        assert "app/" not in t.statement, t.id
