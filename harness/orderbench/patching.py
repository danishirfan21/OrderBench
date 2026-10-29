"""A deliberately strict unified-diff parser and applier.

Only plain text edits are supported: modify, create and delete a file. Renames, copies, mode
changes, symlinks and binary patches are rejected, so the set of paths a patch can affect is
exactly the set of paths named in its ``---``/``+++`` headers.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_UNSUPPORTED = (
    "rename from",
    "rename to",
    "copy from",
    "copy to",
    "similarity index",
    "old mode",
    "new mode",
    "Binary files",
    "GIT binary patch",
)


class PatchError(Exception):
    """The patch is malformed, unsupported, or does not apply."""


@dataclass
class Hunk:
    old_start: int
    old_lines: list[str] = field(default_factory=list)
    new_lines: list[str] = field(default_factory=list)


@dataclass
class FilePatch:
    old_path: str | None  # None => file is created
    new_path: str | None  # None => file is deleted
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def path(self) -> str:
        path = self.new_path or self.old_path
        assert path is not None
        return path

    @property
    def touched(self) -> list[str]:
        return [p for p in (self.old_path, self.new_path) if p is not None]


def _clean_path(raw: str) -> str | None:
    raw = raw.split("\t")[0].strip()
    if raw == "/dev/null":
        return None
    if not (raw.startswith("a/") or raw.startswith("b/")):
        raise PatchError(f"path without a/ or b/ prefix: {raw!r}")
    rel = raw[2:]
    pure = PurePosixPath(rel)
    if (
        not rel
        or "\\" in rel
        or "\x00" in rel
        or pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
        or re.match(r"^[A-Za-z]:", rel)
    ):
        raise PatchError(f"unsafe path: {raw!r}")
    return str(pure)


def parse_patch(text: str) -> list[FilePatch]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    patches: list[FilePatch] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(_UNSUPPORTED):
            raise PatchError(f"unsupported patch feature: {line.split(' ')[0]}")
        if line.startswith("--- "):
            if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
                raise PatchError("'---' header without '+++' header")
            old_path = _clean_path(line[4:])
            new_path = _clean_path(lines[i + 1][4:])
            if old_path and new_path and old_path != new_path:
                raise PatchError("renames are not supported")
            if old_path is None and new_path is None:
                raise PatchError("patch neither creates nor modifies a file")
            fp = FilePatch(old_path, new_path)
            i += 2
            while i < len(lines) and lines[i].startswith("@@"):
                match = _HUNK.match(lines[i])
                if not match:
                    raise PatchError(f"bad hunk header: {lines[i]!r}")
                old_len = int(match.group(2) if match.group(2) is not None else 1)
                new_len = int(match.group(4) if match.group(4) is not None else 1)
                hunk = Hunk(old_start=int(match.group(1)))
                i += 1
                while len(hunk.old_lines) < old_len or len(hunk.new_lines) < new_len:
                    if i >= len(lines):
                        raise PatchError("truncated hunk")
                    body = lines[i]
                    tag, content = body[:1], body[1:]
                    if tag == " " or body == "":
                        hunk.old_lines.append(content)
                        hunk.new_lines.append(content)
                    elif tag == "-":
                        hunk.old_lines.append(content)
                    elif tag == "+":
                        hunk.new_lines.append(content)
                    else:
                        raise PatchError(f"unexpected line in hunk: {body!r}")
                    i += 1
                if len(hunk.old_lines) != old_len or len(hunk.new_lines) != new_len:
                    raise PatchError("hunk line counts do not match its header")
                while i < len(lines) and lines[i].startswith("\\"):
                    i += 1
                fp.hunks.append(hunk)
            if not fp.hunks:
                raise PatchError(f"no hunks for {fp.path}")
            patches.append(fp)
            continue
        if line.startswith(("deleted file mode", "new file mode")) and not line.endswith("100644"):
            raise PatchError(f"unsupported file mode: {line!r}")
        i += 1
    if not patches and any(line.strip() for line in lines):
        raise PatchError("no file patches found in non-empty input")
    return patches


def _apply_hunks(original: list[str], fp: FilePatch) -> list[str]:
    result = list(original)
    shift = 0
    for hunk in fp.hunks:
        expected = hunk.old_start - 1 + shift
        if not hunk.old_lines:
            expected = hunk.old_start + shift  # insertion after line N
        pos = _locate(result, hunk.old_lines, max(expected, 0))
        if pos is None:
            raise PatchError(f"hunk does not apply to {fp.path} near line {hunk.old_start}")
        result[pos : pos + len(hunk.old_lines)] = hunk.new_lines
        shift += len(hunk.new_lines) - len(hunk.old_lines) + (pos - expected)
    return result


def _locate(lines: list[str], block: list[str], expected: int) -> int | None:
    if not block:
        return min(expected, len(lines))
    candidates = sorted(range(len(lines) - len(block) + 1), key=lambda p: abs(p - expected))
    for pos in candidates:
        if lines[pos : pos + len(block)] == block:
            return pos
    return None


def apply_patch(root: Path, patches: list[FilePatch]) -> None:
    """Apply atomically: if any file fails, ``root`` is left untouched."""
    staged: dict[str, list[str] | None] = {}
    for fp in patches:
        if fp.path in staged:
            raise PatchError(f"{fp.path} patched twice")
        target = root / fp.path
        if fp.old_path is None:
            if target.exists():
                raise PatchError(f"{fp.path} already exists")
            original: list[str] = []
        else:
            if not target.is_file() or target.is_symlink():
                raise PatchError(f"{fp.path} does not exist")
            original = target.read_bytes().decode("utf-8").split("\n")
            if original and original[-1] == "":
                original.pop()
        updated = _apply_hunks(original, fp)
        staged[fp.path] = None if fp.new_path is None else updated
    for rel, content in staged.items():
        target = root / rel
        if content is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            data = "\n".join(content) + ("\n" if content else "")
            target.write_bytes(data.encode("utf-8"))


def make_diff(path: str, old: str | None, new: str | None) -> str:
    """Render a git-style diff for one file; ``None`` means the file does not exist."""
    old_lines = (old or "").splitlines(keepends=True)
    new_lines = (new or "").splitlines(keepends=True)
    body = "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="/dev/null" if old is None else f"a/{path}",
            tofile="/dev/null" if new is None else f"b/{path}",
            n=3,
        )
    )
    header = f"diff --git a/{path} b/{path}\n"
    if old is None:
        header += "new file mode 100644\n"
    if new is None:
        header += "deleted file mode 100644\n"
    return header + body
