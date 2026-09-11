from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.models import DashboardSummary, RetrievalRunRequest, RetrievalRunResponse
from app.services.integration_setup import integration_readiness

router = APIRouter(prefix="/api/v1")


def require_access(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    expected = request.app.state.settings.api_access_key
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API access key")


@router.get("/health")
async def health(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
        "demo_mode": settings.demo_mode,
    }


@router.post("/retrieval/run", response_model=RetrievalRunResponse)
async def run_retrieval(
    payload: RetrievalRunRequest,
    request: Request,
    _: None = Depends(require_access),
) -> RetrievalRunResponse:
    return await request.app.state.engine.run(payload)


@router.get("/dashboard", response_model=DashboardSummary)
async def dashboard(request: Request, _: None = Depends(require_access)) -> DashboardSummary:
    return DashboardSummary.model_validate(request.app.state.repository.dashboard())


@router.get("/integrations")
async def integrations(request: Request, _: None = Depends(require_access)) -> dict:
    return {
        "scope": "Offline configuration only; live authentication and execution are unverified.",
        "integrations": integration_readiness(request.app.state.settings),
    }
