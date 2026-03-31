import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table

from app.api import admin


class _Result:
    def __init__(self, row: dict | None):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _SessionContext:
    def __init__(self, rows: list[dict | None]):
        self._rows = list(rows)
        self.executed: list[object] = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt):
        self.executed.append(stmt)
        row = self._rows.pop(0) if self._rows else None
        return _Result(row)

    async def commit(self):
        self.commits += 1


def test_password_hash_roundtrip() -> None:
    password = "my-secret-password"
    hashed = admin._hash_password(password)

    assert "$" in hashed
    assert admin._verify_password(password, hashed) is True
    assert admin._verify_password("wrong-password", hashed) is False


def test_extract_auth_token_from_bearer_header() -> None:
    request = SimpleNamespace(headers={"Authorization": "Bearer abc123"})
    assert admin._extract_auth_token(request) == "abc123"


def test_bootstrap_admin_requires_credentials() -> None:
    app = SimpleNamespace(
        config=SimpleNamespace(ADMIN_LOGIN="", ADMIN_PASS=""),
        db=SimpleNamespace(session=_SessionContext([])),
    )
    with pytest.raises(RuntimeError, match="ADMIN_LOGIN and ADMIN_PASS"):
        asyncio.run(admin.ensure_bootstrap_admin(app))


def test_bootstrap_admin_creates_when_missing(monkeypatch) -> None:
    users_table = Table(
        "api_auth_users",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("username", String),
        Column("password_hash", String),
        Column("is_staff", Boolean),
    )
    monkeypatch.setattr(
        admin,
        "_get_table",
        lambda name: users_table if name == "api_auth_users" else None,
    )

    session = _SessionContext([None])
    app = SimpleNamespace(
        config=SimpleNamespace(ADMIN_LOGIN="admin", ADMIN_PASS="secret"),
        db=SimpleNamespace(session=session),
    )

    asyncio.run(admin.ensure_bootstrap_admin(app))

    assert len(session.executed) == 2
    assert session.commits == 1


def test_bootstrap_admin_elevates_existing_non_staff(monkeypatch) -> None:
    users_table = Table(
        "api_auth_users",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("username", String),
        Column("password_hash", String),
        Column("is_staff", Boolean),
    )
    monkeypatch.setattr(
        admin,
        "_get_table",
        lambda name: users_table if name == "api_auth_users" else None,
    )

    session = _SessionContext([{"id": 7, "is_staff": False}])
    app = SimpleNamespace(
        config=SimpleNamespace(ADMIN_LOGIN="admin", ADMIN_PASS="secret"),
        db=SimpleNamespace(session=session),
    )

    asyncio.run(admin.ensure_bootstrap_admin(app))

    assert len(session.executed) == 2
    assert session.commits == 1


def test_bootstrap_admin_keeps_existing_staff(monkeypatch) -> None:
    users_table = Table(
        "api_auth_users",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("username", String),
        Column("password_hash", String),
        Column("is_staff", Boolean),
    )
    monkeypatch.setattr(
        admin,
        "_get_table",
        lambda name: users_table if name == "api_auth_users" else None,
    )

    session = _SessionContext([{"id": 7, "is_staff": True}])
    app = SimpleNamespace(
        config=SimpleNamespace(ADMIN_LOGIN="admin", ADMIN_PASS="secret"),
        db=SimpleNamespace(session=session),
    )

    asyncio.run(admin.ensure_bootstrap_admin(app))

    assert len(session.executed) == 1
    assert session.commits == 0
