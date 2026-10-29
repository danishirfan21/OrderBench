from __future__ import annotations

from fastapi import APIRouter

from app.deps import DB, ClockDep, CurrentUser, SettingsDep
from app.schemas import LoginIn, TokenOut, UserCreate, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: UserCreate, db: DB, settings: SettingsDep, clock: ClockDep) -> UserOut:
    user = auth_service.create_user(db, settings, clock, body.email, body.password)
    return UserOut.model_validate(user)


@router.post("/token", response_model=TokenOut)
def token(body: LoginIn, db: DB, settings: SettingsDep, clock: ClockDep) -> TokenOut:
    access_token, ttl = auth_service.login(db, settings, clock, body.email, body.password)
    return TokenOut(access_token=access_token, expires_in=ttl)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
