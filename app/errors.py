"""Domain errors. Each carries the HTTP status the API layer should use."""

from __future__ import annotations


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class InsufficientStockError(ConflictError):
    code = "insufficient_stock"

    def __init__(self, product_id: int, requested: int, available: int) -> None:
        super().__init__(f"product {product_id}: requested {requested}, only {available} available")
        self.product_id = product_id
        self.requested = requested
        self.available = available


class AuthenticationError(DomainError):
    status_code = 401
    code = "unauthenticated"


class PermissionDeniedError(DomainError):
    status_code = 403
    code = "forbidden"
