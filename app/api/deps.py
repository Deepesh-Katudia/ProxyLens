"""Shared FastAPI dependencies."""

from fastapi import Request
from pymongo.asynchronous.database import AsyncDatabase

from app.db.client import Document


def get_db(request: Request) -> AsyncDatabase[Document] | None:
    """The app-wide database handle, or None if MongoDB is not configured."""
    db: AsyncDatabase[Document] | None = request.app.state.db
    return db
