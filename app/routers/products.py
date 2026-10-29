from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.deps import DB, AdminUser, CurrentUser, Pagination
from app.errors import ConflictError, NotFoundError
from app.models import Product, StockLevel
from app.pagination import Page, make_page, offset_for
from app.repositories import ProductRepository, StockRepository
from app.schemas import ProductCreate, ProductOut, StockOut, StockSet

router = APIRouter(prefix="/products", tags=["products"])


def _stock_out(stock: StockLevel) -> StockOut:
    return StockOut(
        product_id=stock.product_id,
        on_hand=stock.on_hand,
        reserved=stock.reserved,
        available=stock.on_hand - stock.reserved,
    )


@router.get("", response_model=Page[ProductOut])
def list_products(
    db: DB,
    paging: Pagination,
    q: str | None = None,
    active: bool | None = None,
    min_price: Annotated[int | None, Query(ge=0)] = None,
    max_price: Annotated[int | None, Query(ge=0)] = None,
    sort: Annotated[str, Query(pattern="^-?(id|name|price)$")] = "id",
) -> Page[ProductOut]:
    rows, total = ProductRepository(db).list(
        q=q,
        active=active,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
        offset=offset_for(paging.page, paging.size),
        limit=paging.size,
    )
    items = [ProductOut.model_validate(p) for p in rows]
    return make_page(items, total, paging.page, paging.size)


@router.post("", response_model=ProductOut, status_code=201)
def create_product(body: ProductCreate, db: DB, _admin: AdminUser) -> ProductOut:
    products = ProductRepository(db)
    if products.get_by_sku(body.sku) is not None:
        raise ConflictError(f"sku {body.sku} already exists")
    product = products.add(Product(sku=body.sku, name=body.name, price_cents=body.price_cents))
    StockRepository(db).add(StockLevel(product_id=product.id, on_hand=body.initial_stock))
    db.commit()
    return ProductOut.model_validate(product)


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: DB) -> ProductOut:
    product = ProductRepository(db).get(product_id)
    if product is None:
        raise NotFoundError(f"product {product_id} not found")
    return ProductOut.model_validate(product)


@router.get("/{product_id}/stock", response_model=StockOut)
def get_stock(product_id: int, db: DB, _user: CurrentUser) -> StockOut:
    stock = StockRepository(db).get(product_id)
    if stock is None:
        raise NotFoundError(f"product {product_id} not found")
    return _stock_out(stock)


@router.put("/{product_id}/stock", response_model=StockOut)
def set_stock(product_id: int, body: StockSet, db: DB, _admin: AdminUser) -> StockOut:
    stock = StockRepository(db).get(product_id)
    if stock is None:
        raise NotFoundError(f"product {product_id} not found")
    if body.on_hand < stock.reserved:
        raise ConflictError("on_hand cannot drop below the reserved quantity")
    stock.on_hand = body.on_hand
    db.commit()
    return _stock_out(stock)
