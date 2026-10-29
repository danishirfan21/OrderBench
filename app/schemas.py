"""Pydantic v2 request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from app.timeutil import as_utc

UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth -------------------------------------------------------------------


class UserCreate(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    password: str = Field(min_length=8, max_length=128)


class UserOut(ORMModel):
    id: int
    email: str
    role: str
    is_active: bool


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# --- catalogue --------------------------------------------------------------


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    price_cents: int = Field(gt=0)
    initial_stock: int = Field(default=0, ge=0)

    @field_validator("sku")
    @classmethod
    def _normalise_sku(cls, value: str) -> str:
        return value.strip().upper()


class ProductOut(ORMModel):
    id: int
    sku: str
    name: str
    price_cents: int
    active: bool


class StockOut(BaseModel):
    product_id: int
    on_hand: int
    reserved: int
    available: int


class StockSet(BaseModel):
    on_hand: int = Field(ge=0)


# --- orders -----------------------------------------------------------------


class OrderItemIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=1000)


class OrderCreate(BaseModel):
    items: list[OrderItemIn] = Field(min_length=1, max_length=50)


class OrderItemOut(ORMModel):
    product_id: int
    quantity: int
    unit_price_cents: int


class OrderOut(ORMModel):
    id: int
    user_id: int
    status: str
    total_cents: int
    created_at: UtcDatetime
    items: list[OrderItemOut]


class ReservationOut(BaseModel):
    id: int
    order_id: int
    product_id: int
    quantity: int
    status: str
    expires_at: UtcDatetime
    seconds_remaining: int


class SweepOut(BaseModel):
    expired: int


class AuditOut(ORMModel):
    id: int
    event: str
    detail: str
    user_id: int | None
    created_at: UtcDatetime


# --- billing ----------------------------------------------------------------


class PlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    monthly_price_cents: int = Field(gt=0)


class PlanOut(ORMModel):
    id: int
    name: str
    monthly_price_cents: int


class SubscriptionCreate(BaseModel):
    plan_id: int


class ChangePlanIn(BaseModel):
    plan_id: int


class InvoiceOut(ORMModel):
    id: int
    kind: str
    amount_cents: int
    description: str
    created_at: UtcDatetime


class SubscriptionOut(ORMModel):
    id: int
    user_id: int
    plan_id: int
    anchor_day: int
    status: Literal["active", "cancelled"]
    period_start: UtcDatetime
    period_end: UtcDatetime
    invoices: list[InvoiceOut]
