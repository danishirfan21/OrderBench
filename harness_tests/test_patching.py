from __future__ import annotations

from pathlib import Path

import pytest
from orderbench.patching import PatchError, apply_patch, make_diff, parse_patch


def test_roundtrip(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"one\ntwo\nthree\n")
    apply_patch(tmp_path, parse_patch(make_diff("a.txt", "one\ntwo\nthree\n", "one\n2\nthree\n")))
    assert (tmp_path / "a.txt").read_bytes() == b"one\n2\nthree\n"


def test_failed_hunk_leaves_tree_untouched(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"x\n")
    (tmp_path / "b.txt").write_bytes(b"y\n")
    text = make_diff("a.txt", "x\n", "z\n") + make_diff("b.txt", "NOPE\n", "w\n")
    with pytest.raises(PatchError):
        apply_patch(tmp_path, parse_patch(text))
    assert (tmp_path / "a.txt").read_bytes() == b"x\n"


@pytest.mark.parametrize("path", ["../escape.py", "/abs.py"])
def test_unsafe_paths_rejected(path: str) -> None:
    with pytest.raises(PatchError):
        parse_patch(f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-a\n+b\n")


def test_garbage_is_rejected() -> None:
    with pytest.raises(PatchError):
        parse_patch("rename from a\nrename to b\n")
