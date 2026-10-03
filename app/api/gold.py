"""Gold-set labelling endpoints, used by the /label page."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.security import require_api_key
from app.gold.store import GoldItem, GoldItemSummary, GoldLabel, GoldStore

router = APIRouter(prefix="/gold", tags=["gold"])


class GoldProgress(BaseModel):
    total: int
    labelled: int
    skipped: int
    items: list[GoldItemSummary]


def get_gold_store(request: Request) -> GoldStore:
    store: GoldStore = request.app.state.gold_store
    return store


@router.get("/items", response_model=GoldProgress)
def list_gold_items(store: Annotated[GoldStore, Depends(get_gold_store)]) -> GoldProgress:
    items = store.list_items()
    return GoldProgress(
        total=len(items),
        labelled=sum(i.status == "labelled" for i in items),
        skipped=sum(i.status == "skipped" for i in items),
        items=items,
    )


@router.get("/items/{item_id}", response_model=GoldItem)
def get_gold_item(item_id: str, store: Annotated[GoldStore, Depends(get_gold_store)]) -> GoldItem:
    item = store.get_item(item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown gold item")
    return item


@router.put(
    "/items/{item_id}/label",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_key)],
)
def save_gold_label(
    item_id: str, label: GoldLabel, store: Annotated[GoldStore, Depends(get_gold_store)]
) -> None:
    try:
        store.save_label(item_id, label)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown gold item") from None
