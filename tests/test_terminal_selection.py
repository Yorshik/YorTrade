import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from app.api import admin


class _Result:
    def __init__(self, row: dict | None):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _SessionContext:
    def __init__(self, row: dict | None):
        self._result = _Result(row)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt):
        _ = stmt
        return self._result

    async def commit(self):
        return None


def _request(query: dict[str, str], *, db=None):
    return SimpleNamespace(
        query=query,
        headers={},
        app=SimpleNamespace(
            db=db,
            config=SimpleNamespace(API_AUTH_TTL_HOURS=24),
        ),
    )


def test_delete_user_by_tg_id_requires_platform(monkeypatch) -> None:
    monkeypatch.setattr(
        admin, "_ensure_staff", AsyncMock(return_value={"id": 1, "is_staff": True})
    )
    request = _request({"tg_user_id": "123"})

    with pytest.raises(web.HTTPBadRequest) as exc:
        asyncio.run(admin.delete_user_legacy(request))
    assert "platform" in (exc.value.text or "")


def test_delete_user_by_tg_id_and_platform_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr(
        admin, "_ensure_staff", AsyncMock(return_value={"id": 1, "is_staff": True})
    )
    db = SimpleNamespace(
        session=_SessionContext({"id": 1, "tg_user_id": 123, "platform": "TG"})
    )
    request = _request({"tg_user_id": "123", "platform": "TG"}, db=db)

    response = asyncio.run(admin.delete_user_legacy(request))
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["deleted_user"]["id"] == 1
    assert payload["deleted_user"]["platform"] == "TG"
