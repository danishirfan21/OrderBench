from __future__ import annotations

from collections.abc import Callable

from app.pagination import make_page, page_count
from tests.conftest import World


def test_page_count() -> None:
    assert page_count(0, 20) == 0
    assert page_count(1, 20) == 1
    assert page_count(20, 20) == 1
    assert page_count(21, 20) == 2


def test_make_page_carries_metadata() -> None:
    page = make_page(["a"], total=41, page=3, size=20)
    assert (page.total, page.page, page.size, page.pages) == (41, 3, 20, 3)


def test_list_metadata_reports_total_and_pages(
    world: World, make_products: Callable[[int], None]
) -> None:
    make_products(47)
    body = world.client.get("/products", params={"size": 10}).json()
    assert body["total"] == 50
    assert body["pages"] == 5
    assert body["size"] == 10


def test_page_past_the_end_is_empty(world: World) -> None:
    body = world.client.get("/products", params={"page": 99}).json()
    assert body["items"] == []
    assert body["total"] == 3


def test_invalid_paging_parameters_rejected(world: World) -> None:
    assert world.client.get("/products", params={"page": 0}).status_code == 422
    assert world.client.get("/products", params={"size": 0}).status_code == 422
    assert world.client.get("/products", params={"size": 101}).status_code == 422
