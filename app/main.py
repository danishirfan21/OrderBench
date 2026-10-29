"""Application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.clock import Clock, SystemClock
from app.config import Settings, get_settings
from app.database import make_engine, make_session_factory
from app.errors import DomainError
from app.models import Base
from app.routers import admin, auth, billing, orders, products


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="OrderBench reference service", version="1.0.0")
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    app.state.settings = settings
    app.state.clock = clock or SystemClock()
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    @app.exception_handler(DomainError)
    async def _domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "invalid request",
                    "details": details,
                }
            },
        )

    for module in (auth, products, orders, admin, billing):
        app.include_router(module.router)
    return app
