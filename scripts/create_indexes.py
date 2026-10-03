"""Create (or update) the Atlas Vector Search and Atlas Search indexes on `regulations`.

uv run python -m scripts.create_indexes [--no-text]
"""

import argparse
import asyncio
import logging
import sys

from app.config import get_settings
from app.db.client import create_client
from app.db.collections import REGULATIONS
from app.db.indexes import ensure_search_indexes, regulation_index_models, wait_until_queryable


async def run(with_text: bool) -> None:
    settings = get_settings()
    client = create_client(settings)
    if client is None:
        raise SystemExit("MONGODB_URI is not set")
    db = client[settings.mongodb_db]
    try:
        if REGULATIONS not in await db.list_collection_names():
            await db.create_collection(REGULATIONS)
        collection = db[REGULATIONS]
        models = regulation_index_models(settings.embedding_dim, with_text=with_text)
        await ensure_search_indexes(collection, models)
        await wait_until_queryable(collection, [m.document["name"] for m in models])
        logging.info("Indexes ready")
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-text", action="store_true", help="skip the full-text index")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run(with_text=not args.no_text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
