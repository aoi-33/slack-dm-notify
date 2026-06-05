from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.models  # noqa: F401  (Base.metadata 登録)
    from app.db import Base, engine

    Base.metadata.create_all(bind=engine)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Slack DM Notify", lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key)

    from app.routes import auth_ui, notify, types_ui

    app.include_router(notify.router)
    app.include_router(auth_ui.router)
    app.include_router(types_ui.router)
    return app


app = create_app()
