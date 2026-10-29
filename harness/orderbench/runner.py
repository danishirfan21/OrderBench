"""Test execution backends.

``DockerBackend`` is the reference: a pinned image, ``--network none``, a read-only root
filesystem, all capabilities dropped, a non-root user. ``LocalBackend`` runs the same pytest
command in a subprocess on the host with the in-process network guard only; it exists so the
environment can be developed and validated on machines without Docker, and its verdicts report
``image_digest == "local-sandbox"``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

IMAGE_TAG = "orderbench-env:1.0.0"
HARNESS_DIR = Path(__file__).resolve().parent.parent  # directory containing the orderbench package


@dataclass
class RunResult:
    results: dict[str, str]  # node id -> "passed" | "failed" | "incomplete"
    timed_out: bool
    exitstatus: int | None


def _pytest_args(targets: list[str]) -> list[str]:
    return [
        "-m",
        "pytest",
        "-c",
        "pytest.ini",
        "-p",
        "orderbench.guard",
        "-p",
        "no:cacheprovider",
        "--rootdir",
        ".",
        "-q",
        *targets,
    ]


def _read_results(path: Path) -> tuple[dict[str, str], int | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return dict(data["results"]), int(data["exitstatus"])
    except (OSError, ValueError, KeyError):
        return {}, None


class LocalBackend:
    name = "local"

    def image_digest(self) -> str:
        return "local-sandbox"

    def run(self, workspace: Path, targets: list[str], timeout: int) -> RunResult:
        with tempfile.TemporaryDirectory(prefix="orderbench-out-") as out:
            results_file = Path(out) / "results.json"
            env = {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "PYTHONPATH": os.pathsep.join([str(workspace), str(HARNESS_DIR)]),
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "ORDERBENCH_EVAL": "1",
                "ORDERBENCH_RESULTS": str(results_file),
                "TZ": "UTC",
                "LC_ALL": "C.UTF-8",
                "TMPDIR": out,
                "TEMP": out,
                "TMP": out,
            }
            for key in ("SYSTEMROOT", "PATH", "HOME", "USERPROFILE"):
                if key in os.environ:
                    env[key] = os.environ[key]
            proc = subprocess.Popen(
                [sys.executable, *_pytest_args(targets)],
                cwd=workspace,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                return RunResult({}, True, None)
            results, status = _read_results(results_file)
            return RunResult(results, False, status)


class DockerBackend:
    name = "docker"

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def _docker(self, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, check=False, timeout=timeout
        )

    def ensure_image(self) -> str:
        inspect = self._docker("image", "inspect", "--format", "{{.Id}}", IMAGE_TAG)
        if inspect.returncode != 0:
            build = self._docker(
                "build", "--network", "host", "-t", IMAGE_TAG, str(self.repo_root), timeout=1800
            )
            if build.returncode != 0:
                raise RuntimeError(f"docker build failed:\n{build.stderr[-2000:]}")
            inspect = self._docker("image", "inspect", "--format", "{{.Id}}", IMAGE_TAG)
        return inspect.stdout.strip()

    def image_digest(self) -> str:
        return self.ensure_image()

    def run(self, workspace: Path, targets: list[str], timeout: int) -> RunResult:
        self.ensure_image()
        name = f"orderbench-{uuid.uuid4().hex[:12]}"
        with tempfile.TemporaryDirectory(prefix="orderbench-out-") as out:
            os.chmod(out, 0o777)
            cmd = [
                "docker", "run", "--rm", "--name", name,
                "--network", "none",
                "--read-only", "--tmpfs", "/tmp:rw,size=256m",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--pids-limit", "256", "--memory", "1g", "--cpus", "2",
                "--user", "10001:10001",
                "-v", f"{workspace}:/work:ro",
                "-v", f"{HARNESS_DIR}:/opt/orderbench:ro",
                "-v", f"{out}:/out:rw",
                "-w", "/work",
                "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONHASHSEED=0",
                "-e", "PYTHONPATH=/work:/opt/orderbench",
                "-e", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                "-e", "ORDERBENCH_EVAL=1", "-e", "ORDERBENCH_RESULTS=/out/results.json",
                "-e", "TZ=UTC", "-e", "LC_ALL=C.UTF-8",
                IMAGE_TAG,
                "python", *_pytest_args(targets),
            ]  # fmt: skip
            try:
                subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
            except subprocess.TimeoutExpired:
                self._docker("kill", name)
                return RunResult({}, True, None)
            results, status = _read_results(Path(out) / "results.json")
            return RunResult(results, False, status)


Backend = LocalBackend | DockerBackend


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(["docker", "info"], capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def select_backend(repo_root: Path, choice: str | None = None) -> Backend:
    choice = choice or os.environ.get("ORDERBENCH_BACKEND", "auto")
    if choice == "local":
        return LocalBackend()
    if choice == "docker":
        if not docker_available():
            raise RuntimeError("--backend docker requested but the docker daemon is unavailable")
        return DockerBackend(repo_root)
    if choice == "auto":
        if docker_available():
            return DockerBackend(repo_root)
        print(
            "orderbench: docker unavailable, falling back to the local sandbox backend "
            "(network blocked in-process only)",
            file=sys.stderr,
        )
        return LocalBackend()
    raise RuntimeError(f"unknown backend {choice!r} (expected auto, docker or local)")
