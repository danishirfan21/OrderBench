from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import World


@pytest.mark.parametrize(
    "quantity",
    [2.5, "2.5", 0.4, 0, "0", -3, -0.0],
    ids=["float-2.5", "str-2.5", "float-0.4", "int-0", "str-0", "int-neg", "float-negzero"],
)
def test_non_whole_or_non_positive_quantities_are_rejected(world: World, quantity: Any) -> None:
    pid = world.product_ids["WIDGET"]
    resp = world.client.post(
        "/orders",
        json={"items": [{"product_id": pid, "quantity": quantity}]},
        headers=world.headers("alice"),
    )
    assert resp.status_code == 422
    assert world.stock("WIDGET") == (10, 0)
    listing = world.client.get("/orders", headers=world.headers("alice")).json()
    assert listing["total"] == 0


def test_a_bad_line_rejects_the_whole_request(world: World) -> None:
    body = {
        "items": [
            {"product_id": world.product_ids["WIDGET"], "quantity": 2},
            {"product_id": world.product_ids["GADGET"], "quantity": 1.5},
        ]
    }
    resp = world.client.post("/orders", json=body, headers=world.headers("alice"))
    assert resp.status_code == 422
    assert world.stock("WIDGET") == (10, 0)
