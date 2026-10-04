"""Liveness endpoint."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel
from pymongo.asynchronous.database import AsyncDatabase

from app.api.deps import get_db
from app.db.client import Document, ping

router = APIRouter(tags=["health"])

DbStatus = Literal["ok", "unreachable", "not_configured"]
ModelStatus = Literal["loaded", "not_loaded"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: DbStatus
    model: ModelStatus


async def _db_status(db: AsyncDatabase[Document] | None) -> DbStatus:
    if db is None:
        return "not_configured"
    return "ok" if await ping(db) else "unreachable"


@router.get("/healthz", response_model=HealthResponse)
async def healthz(
    request: Request,
    response: Response,
    db: Annotated[AsyncDatabase[Document] | None, Depends(get_db)],
) -> HealthResponse:
    db_status = await _db_status(db)
    # The model loads on the first analysis job, so "not_loaded" is not an error.
    factory = getattr(request.app.state, "pipeline_factory", None)
    loaded = factory is not None and factory.student_loaded
    model: ModelStatus = "loaded" if loaded else "not_loaded"
    if db_status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", db=db_status, model=model)
    return HealthResponse(status="ok", db=db_status, model=model)
