"""Liveness endpoint."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from pymongo.asynchronous.database import AsyncDatabase

from app.api.deps import get_db
from app.db.client import Document, ping

router = APIRouter(tags=["health"])

DbStatus = Literal["ok", "unreachable", "not_configured"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: DbStatus
    model: Literal["loaded", "not_loaded"]


async def _db_status(db: AsyncDatabase[Document] | None) -> DbStatus:
    if db is None:
        return "not_configured"
    return "ok" if await ping(db) else "unreachable"


@router.get("/healthz", response_model=HealthResponse)
async def healthz(
    response: Response,
    db: Annotated[AsyncDatabase[Document] | None, Depends(get_db)],
) -> HealthResponse:
    db_status = await _db_status(db)
    # The student model is wired in Phase 4; until then it is never loaded.
    if db_status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", db=db_status, model="not_loaded")
    return HealthResponse(status="ok", db=db_status, model="not_loaded")
