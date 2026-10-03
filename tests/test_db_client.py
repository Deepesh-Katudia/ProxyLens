from app.config import Settings
from app.db.client import create_client, ping


def test_create_client_returns_none_without_uri() -> None:
    assert create_client(Settings(_env_file=None)) is None


async def test_ping_returns_false_when_server_unreachable() -> None:
    # Port 1 is never a MongoDB server; a short timeout keeps the test fast.
    settings = Settings(_env_file=None, mongodb_uri="mongodb://127.0.0.1:1", mongodb_timeout_ms=200)
    client = create_client(settings)
    assert client is not None
    try:
        assert await ping(client["proxylens"]) is False
    finally:
        await client.close()
