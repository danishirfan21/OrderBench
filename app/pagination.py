"""Page/size pagination shared by every list endpoint. Pages are 1-indexed."""

from __future__ import annotations

from pydantic import BaseModel


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int


def offset_for(page: int, size: int) -> int:
    return (page - 1) * size


def page_count(total: int, size: int) -> int:
    return (total + size - 1) // size


def make_page[T](items: list[T], total: int, page: int, size: int) -> Page[T]:
    return Page[T](items=items, total=total, page=page, size=size, pages=page_count(total, size))
