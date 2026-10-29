from __future__ import annotations

import os
import socket

import pytest


@pytest.mark.skipif(
    os.environ.get("ORDERBENCH_EVAL") != "1", reason="only meaningful under the evaluation harness"
)
def test_outbound_connections_are_blocked() -> None:
    with pytest.raises(OSError):
        socket.create_connection(("93.184.216.34", 80), timeout=1)
    with pytest.raises(OSError):
        socket.getaddrinfo("example.com", 80)
