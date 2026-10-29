from __future__ import annotations

import pytest

from app.errors import AuthenticationError
from app.security import decode_token, hash_password, issue_token, verify_password
from tests.conftest import FROZEN_NOW


def test_hash_roundtrip_and_salting() -> None:
    a = hash_password("hunter2hunter2", 4)
    b = hash_password("hunter2hunter2", 4)
    assert a != b
    assert verify_password("hunter2hunter2", a)
    assert not verify_password("hunter3hunter3", a)


def test_verify_rejects_malformed_hash() -> None:
    assert not verify_password("x", "not-a-hash")


def test_token_roundtrip() -> None:
    token = issue_token(7, "s", FROZEN_NOW, 60)
    assert decode_token(token, "s", FROZEN_NOW) == 7


def test_token_wrong_secret_rejected() -> None:
    token = issue_token(7, "s", FROZEN_NOW, 60)
    with pytest.raises(AuthenticationError):
        decode_token(token, "other", FROZEN_NOW)
