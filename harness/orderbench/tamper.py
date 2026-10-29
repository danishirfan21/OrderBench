"""Reward-integrity checks.

A candidate patch may touch Python source files under ``app/`` and nothing else. That is an
explicit allowlist: tests, configuration, plugins, conftest files, ``sitecustomize.py`` and the
harness itself are unreachable simply because they are not on the list. A second, narrower
content scan rejects added lines that try to interfere with the test run from inside allowed
files, and a hash comparison after the run catches anything that slipped through at runtime.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from orderbench.patching import FilePatch

# The allowlist: python modules under app/, nested packages allowed.
ALLOWED_PATH = re.compile(r"^app/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py$")

# Files that execute implicitly at interpreter or pytest start-up, even inside app/.
FORBIDDEN_BASENAMES = frozenset(
    {"conftest.py", "sitecustomize.py", "usercustomize.py", "__main__.py", "pytest_plugin.py"}
)

# Added lines matching these are rejected even in allowed files.
FORBIDDEN_CONTENT: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("touches pytest internals", re.compile(r"\b_?pytest\b|\bconftest\b|\bpytest_\w+")),
    ("tampers with sys.modules/builtins", re.compile(r"sys\.modules|\bbuiltins\b|__builtins__")),
    (
        "dynamic import or code execution",
        re.compile(r"\bimportlib\b|\b(__import__|exec|eval)\b\s*\("),
    ),
    (
        "exit/atexit/trace hooks",
        re.compile(r"\batexit\b|sys\.exit|os\._exit|settrace|setprofile|excepthook"),
    ),
    (
        "monkeypatches assertion behaviour",
        re.compile(r"\bAssertionError\b|assertrepr|\bunittest\b|\bmock\b"),
    ),
    (
        "process or network access",
        re.compile(r"\b(subprocess|socket|ctypes|os\.system|os\.popen)\b"),
    ),
    (
        "references the harness or tests",
        re.compile(r"orderbench|ORDERBENCH_|tests/|\bsitecustomize\b"),
    ),
)


@dataclass(frozen=True)
class Violation:
    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}: {self.reason}"


def _path_violation(path: str) -> str | None:
    basename = path.rsplit("/", 1)[-1]
    if basename in FORBIDDEN_BASENAMES:
        return "implicit-execution file (conftest/sitecustomize/plugin) is never modifiable"
    if ALLOWED_PATH.match(path):
        return None
    if path.startswith("tests/") or basename.startswith("test_") or basename.endswith("_test.py"):
        return "tests are held out and read-only"
    if path in {"pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "setup.py"}:
        return "test configuration is read-only"
    if path.startswith(("harness/", "tasks/", "orderbench/")):
        return "the evaluation harness is read-only"
    return "outside the modifiable allowlist (python modules under app/)"


def check_patch(patches: list[FilePatch]) -> list[Violation]:
    violations: list[Violation] = []
    for fp in patches:
        for path in fp.touched:
            reason = _path_violation(path)
            if reason:
                violations.append(Violation(path, reason))
        if fp.new_path is None or _path_violation(fp.new_path):
            continue
        for hunk in fp.hunks:
            old = set(hunk.old_lines)
            for line in hunk.new_lines:
                if line in old:
                    continue  # unchanged context, not introduced by this patch
                for reason, pattern in FORBIDDEN_CONTENT:
                    if pattern.search(line):
                        violations.append(
                            Violation(fp.new_path, f"added code {reason}: {line.strip()!r}")
                        )
    return violations


def snapshot(root: Path, exclude_dirs: tuple[str, ...] = ("app",)) -> dict[str, str]:
    """Hash every file outside the modifiable tree; used before and after the test run."""
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir() or "__pycache__" in rel.split("/") or rel.split("/")[0] in exclude_dirs:
            continue
        digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(
        set(before) ^ set(after) | {k for k in before if k in after and before[k] != after[k]}
    )
