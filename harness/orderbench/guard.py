"""Pytest plugin loaded by the harness (``-p orderbench.guard``).

* Blocks every non-loopback network operation, in addition to the container's ``--network none``.
* Records the outcome of every test to the file named by ``ORDERBENCH_RESULTS``, keyed by the
  exact pytest node id, so verdicts never depend on parsing console output.

Deliberately stdlib-only: it is imported inside the evaluation container.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
from typing import Any

_LOOPBACK_NAMES = {"localhost", "localhost.localdomain"}
_results: dict[str, str] = {}
_REAL_GETADDRINFO = socket.getaddrinfo
_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex


class NetworkDisabledError(OSError):
    pass


def _is_loopback(host: Any) -> bool:
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    if not isinstance(host, str):
        return False
    if host in _LOOPBACK_NAMES or host == "":
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _check_address(address: Any) -> None:
    if isinstance(address, (str, bytes)):  # AF_UNIX path
        return
    if isinstance(address, tuple) and address and _is_loopback(address[0]):
        return
    raise NetworkDisabledError(f"network access is disabled during evaluation: {address!r}")


def _connect(self: socket.socket, address: Any) -> None:
    _check_address(address)
    return _REAL_CONNECT(self, address)


def _connect_ex(self: socket.socket, address: Any) -> int:
    _check_address(address)
    return _REAL_CONNECT_EX(self, address)


def _getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    if not _is_loopback(host):
        raise NetworkDisabledError(f"name resolution is disabled during evaluation: {host!r}")
    return _REAL_GETADDRINFO(host, *args, **kwargs)


def pytest_configure(config: Any) -> None:
    socket.socket.connect = _connect  # type: ignore[method-assign,assignment]
    socket.socket.connect_ex = _connect_ex  # type: ignore[method-assign,assignment]
    socket.getaddrinfo = _getaddrinfo


def pytest_runtest_logreport(report: Any) -> None:
    # A test passes only if setup, call and teardown all pass.
    nodeid = report.nodeid
    if report.when == "call":
        outcome = (
            "passed" if report.outcome == "passed" and not hasattr(report, "wasxfail") else "failed"
        )
        if _results.get(nodeid) != "failed":
            _results[nodeid] = outcome
    elif report.outcome != "passed":
        _results[nodeid] = "failed"
    elif report.when == "setup":
        _results.setdefault(nodeid, "incomplete")


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    path = os.environ.get("ORDERBENCH_RESULTS")
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"exitstatus": int(exitstatus), "results": _results}, handle, sort_keys=True)
