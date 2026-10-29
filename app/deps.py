"""FastAPI dependencies and authorization helpers."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings
from app.errors import AuthenticationError, PermissionDeniedError
from app.models import User
from app.services import auth_service


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def get_db(request: Request) -> Iterator[Session]:
    db: Session = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


DB = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ClockDep = Annotated[Clock, Depends(get_clock)]


def get_current_user(
    db: DB,
    settings: SettingsDep,
    clock: ClockDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("missing bearer token")
    return auth_service.user_from_token(db, settings, clock, authorization[7:].strip())


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise PermissionDeniedError("admin only")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def ensure_owner_or_admin(user: User, owner_id: int) -> None:
    if user.role != "admin" and user.id != owner_id:
        raise PermissionDeniedError("you do not have access to this resource")


class PageParams:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1)] = 1,
        size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> None:
        self.page = page
        self.size = size


Pagination = Annotated[PageParams, Depends()]
