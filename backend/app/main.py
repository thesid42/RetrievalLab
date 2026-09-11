from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.hotdata import HotdataQueryEngine
from app.adapters.sponsors import (
    CogneeMemoryConstructor,
    HydraMemoryGraph,
    RocketRideOrchestrator,
    RotePlaybook,
)
from app.api.routes import router
from app.config import Settings, get_settings
from app.services.engine import RetrievalEngine
from app.services.retrieval import Corpus
from app.services.state import StateRepository


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application with explicit settings for tests and deployments.

    The module-level ``app`` below remains the Uvicorn entry point. Supplying settings
    here avoids reading a developer's .env file when an isolated test app is needed.
    """
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = app_settings
        if not settings.corpus_path.is_file():
            raise RuntimeError(f"Corpus file does not exist: {settings.corpus_path}")
        corpus = Corpus(settings.corpus_path, demo_mode=settings.demo_mode)
        repository = StateRepository(settings.state_path, corpus_version=corpus.version)
        app.state.settings = settings
        app.state.repository = repository
        app.state.engine = RetrievalEngine(
            settings=settings,
            state=repository,
            hotdata=HotdataQueryEngine(settings, corpus),
            rocketride=RocketRideOrchestrator(settings),
            cognee=CogneeMemoryConstructor(settings),
            hydra=HydraMemoryGraph(settings, repository),
            rote=RotePlaybook(settings, repository),
        )
        yield

    api_app = FastAPI(title=app_settings.app_name, version="0.1.0", lifespan=lifespan)
    api_app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )
    api_app.include_router(router)
    return api_app


settings = get_settings()
app = create_app(settings)
