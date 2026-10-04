"""Debug endpoint for RAG: inspect what the retriever returns for a query."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pymongo.asynchronous.database import AsyncDatabase

from app.api.deps import get_db
from app.db.client import Document
from app.db.collections import REGULATIONS
from app.retrieval.embeddings import Embedder
from app.retrieval.search import DEFAULT_K, retrieve
from app.schemas.regulation import RegulationHit, RegulationView
from app.schemas.resolution import ResolutionType

router = APIRouter(prefix="/regulations", tags=["regulations"])

MAX_K = 20


def get_embedder(request: Request) -> Embedder:
    embedder: Embedder = request.app.state.embedder
    return embedder


@router.get("/search", response_model=list[RegulationHit])
async def search_regulations(
    db: Annotated[AsyncDatabase[Document] | None, Depends(get_db)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    q: Annotated[str, Query(min_length=3, max_length=500)],
    resolution_type: Annotated[ResolutionType | None, Query(alias="type")] = None,
    k: Annotated[int, Query(ge=1, le=MAX_K)] = DEFAULT_K,
    hybrid: bool = False,
) -> list[RegulationHit]:
    if db is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database not configured")
    return await retrieve(db[REGULATIONS], embedder, q, resolution_type, k, hybrid=hybrid)


@router.get("/{regulation_id}", response_model=RegulationView)
async def get_regulation(
    regulation_id: str,
    db: Annotated[AsyncDatabase[Document] | None, Depends(get_db)],
) -> RegulationView:
    if db is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database not configured")
    doc = await db[REGULATIONS].find_one({"_id": regulation_id}, {"embedding": 0})
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown regulation")
    return RegulationView.model_validate({**doc, "id": doc["_id"]})
