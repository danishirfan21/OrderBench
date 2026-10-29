"""Task loading and schema validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DIFFICULTIES = ("easy", "medium", "hard")
_NODE_ID = re.compile(r"^tests/[A-Za-z0-9_./-]+\.py::[A-Za-z0-9_]+(\[.*\])?$")
HELD_OUT_DIR = "tests/held_out"


class TaskError(Exception):
    pass


@dataclass(frozen=True)
class Trap:
    shallow_patch: str
    description: str
    why_it_fails: str


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    difficulty: str
    bug_class: str
    statement: str
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...]
    timeout_seconds: int
    directory: Path
    trap: Trap | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def break_patch(self) -> Path:
        return self.directory / "break.patch"

    @property
    def golden_patch(self) -> Path:
        return self.directory / "golden.patch"

    @property
    def tests_dir(self) -> Path:
        return self.directory / "tests"

    @property
    def held_out_prefix(self) -> str:
        return f"{HELD_OUT_DIR}/{self.id}/"


def load_task(directory: Path) -> Task:
    spec_path = directory / "task.yaml"
    try:
        raw = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TaskError(f"{spec_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise TaskError(f"{spec_path}: expected a mapping")
    required = (
        "id",
        "title",
        "difficulty",
        "bug_class",
        "statement",
        "fail_to_pass",
        "pass_to_pass",
        "timeout_seconds",
    )
    missing = [k for k in required if k not in raw]
    if missing:
        raise TaskError(f"{spec_path}: missing keys {missing}")
    if raw["id"] != directory.name or not re.fullmatch(r"[a-z][a-z0-9_]*", str(raw["id"])):
        raise TaskError(f"{spec_path}: id must equal the directory name and be snake_case")
    if raw["difficulty"] not in DIFFICULTIES:
        raise TaskError(f"{spec_path}: difficulty must be one of {DIFFICULTIES}")
    if not isinstance(raw["timeout_seconds"], int) or raw["timeout_seconds"] <= 0:
        raise TaskError(f"{spec_path}: timeout_seconds must be a positive integer")
    for key in ("fail_to_pass", "pass_to_pass"):
        ids = raw[key]
        if not isinstance(ids, list) or not ids:
            raise TaskError(f"{spec_path}: {key} must be a non-empty list")
        for node in ids:
            if not _NODE_ID.match(str(node)):
                raise TaskError(f"{spec_path}: bad node id {node!r}")
        if len(set(ids)) != len(ids):
            raise TaskError(f"{spec_path}: duplicate ids in {key}")
    prefix = f"{HELD_OUT_DIR}/{raw['id']}/"
    if not all(n.startswith(prefix) for n in raw["fail_to_pass"]):
        raise TaskError(f"{spec_path}: fail_to_pass ids must live under {prefix}")
    if set(raw["fail_to_pass"]) & set(raw["pass_to_pass"]):
        raise TaskError(f"{spec_path}: fail_to_pass and pass_to_pass overlap")
    for name in ("break.patch", "golden.patch"):
        if not (directory / name).is_file():
            raise TaskError(f"{directory}: missing {name}")
    if not list((directory / "tests").glob("test_*.py")):
        raise TaskError(f"{directory}: tests/ has no test_*.py")
    trap = None
    if raw.get("trap"):
        t = raw["trap"]
        if not all(k in t for k in ("shallow_patch", "description", "why_it_fails")):
            raise TaskError(f"{spec_path}: trap needs shallow_patch, description, why_it_fails")
        if not (directory / t["shallow_patch"]).is_file():
            raise TaskError(f"{spec_path}: trap patch {t['shallow_patch']} missing")
        trap = Trap(t["shallow_patch"], t["description"].strip(), t["why_it_fails"].strip())
    return Task(
        id=raw["id"],
        title=raw["title"],
        difficulty=raw["difficulty"],
        bug_class=raw["bug_class"],
        statement=raw["statement"].strip(),
        fail_to_pass=tuple(raw["fail_to_pass"]),
        pass_to_pass=tuple(raw["pass_to_pass"]),
        timeout_seconds=raw["timeout_seconds"],
        directory=directory,
        trap=trap,
    )


def load_all(tasks_dir: Path) -> list[Task]:
    dirs = sorted(p for p in tasks_dir.iterdir() if (p / "task.yaml").is_file())
    return [load_task(d) for d in dirs]
