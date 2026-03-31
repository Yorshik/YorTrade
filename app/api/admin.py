import enum
import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from aiohttp import web
from apispec import APISpec
from sqlalchemy import asc, delete, desc, func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.schema import Table
from sqlalchemy.sql.sqltypes import BIGINT, Boolean, DateTime, Enum, Float, Integer

from app.api.models import ApiAuthSession, ApiAuthUser  # noqa: F401

# Ensure models are imported so Base.metadata is fully populated.
from app.data.models import Asset, Phrase  # noqa: F401
from app.market.models import (  # noqa: F401
    ActiveEvent,
    Company,
    Deal,
    EventTemplate,
    Game,
    GameAsset,
    GameRuntimeState,
    InsiderInfo,
    News,
    Portfolio,
    PriceHistory,
)
from app.store.database.base import Base
from app.users.models import AchievementStats, Player, User  # noqa: F401

RESERVED_QUERY_KEYS = {"limit", "offset", "order_by", "order_dir"}
AUTH_TOKEN_HEADER = "X-Auth-Token"
AUTH_BEARER_PREFIX = "bearer "
logger = logging.getLogger(__name__)


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _serialize_value(value) for key, value in row.items()}


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def _parse_enum(column_type: Enum, value: Any) -> Any:
    enum_class = getattr(column_type, "enum_class", None)
    if enum_class is None:
        return value
    if isinstance(value, enum_class):
        return value

    raw = str(value).strip()
    for member in enum_class:
        if (
            raw.lower() == member.name.lower()
            or raw.lower() == str(member.value).lower()
        ):
            return member
    return value


def _coerce_value(column, value: Any) -> Any:
    if value is None:
        return None
    column_type = column.type
    if isinstance(column_type, (Integer, BIGINT)):
        return int(value)
    if isinstance(column_type, Float):
        return float(value)
    if isinstance(column_type, Boolean):
        return _parse_bool(value)
    if isinstance(column_type, DateTime):
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))
    if isinstance(column_type, Enum):
        return _parse_enum(column_type, value)
    return value


def _available_tables() -> dict[str, Table]:
    return dict(Base.metadata.tables)


def _get_table(table_name: str) -> Table:
    tables = _available_tables()
    table = tables.get(table_name)
    if table is None:
        raise web.HTTPNotFound(
            text=json.dumps({"error": f"Unknown table: {table_name}"}),
            content_type="application/json",
        )
    return table


def _single_pk_column(table: Table):
    pk_columns = list(table.primary_key.columns)
    if len(pk_columns) != 1:
        raise web.HTTPBadRequest(
            text=json.dumps(
                {
                    "error": (
                        f"Table '{table.name}' has composite primary key. "
                        "Use /api/{table}?column=value filters instead."
                    )
                }
            ),
            content_type="application/json",
        )
    return pk_columns[0]


async def _read_json(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": f"Invalid JSON body: {exc}"}),
            content_type="application/json",
        ) from exc
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "JSON body must be an object"}),
            content_type="application/json",
        )
    return body


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        200_000,
    ).hex()
    return f"{salt}${digest}"


def _verify_password(password: str, stored_hash: str) -> bool:
    salt, sep, expected_digest = stored_hash.partition("$")
    if not sep or not salt or not expected_digest:
        return False
    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        200_000,
    ).hex()
    return hmac.compare_digest(actual_digest, expected_digest)


async def ensure_bootstrap_admin(app) -> None:
    username = str(getattr(app.config, "ADMIN_LOGIN", "") or "").strip()
    password = str(getattr(app.config, "ADMIN_PASS", "") or "")
    if not username or not password:
        raise RuntimeError(
            "Set ADMIN_LOGIN and ADMIN_PASS in .env to bootstrap admin account"
        )

    users = _get_table("api_auth_users")
    select_stmt = (
        select(users.c.id, users.c.is_staff)
        .where(users.c.username == username)
        .limit(1)
    )
    async with app.db.session as session:
        existing = (await session.execute(select_stmt)).mappings().first()
        if existing is None:
            await session.execute(
                insert(users).values(
                    username=username,
                    password_hash=_hash_password(password),
                    is_staff=True,
                )
            )
            await session.commit()
            logger.info("Bootstrap admin created username=%s", username)
            return

        if not bool(existing["is_staff"]):
            await session.execute(
                update(users).where(users.c.id == existing["id"]).values(is_staff=True)
            )
            await session.commit()
            logger.info("Bootstrap admin elevated to staff username=%s", username)


def _extract_auth_token(request: web.Request) -> str | None:
    authorization = (request.headers.get("Authorization") or "").strip()
    if authorization.lower().startswith(AUTH_BEARER_PREFIX):
        bearer_token = authorization[len(AUTH_BEARER_PREFIX) :].strip()
        if bearer_token:
            return bearer_token
    token = (request.headers.get(AUTH_TOKEN_HEADER) or "").strip()
    return token or None


def _is_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    normalized = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    return normalized <= datetime.now(timezone.utc)


async def _get_authenticated_user(request: web.Request) -> dict[str, Any] | None:
    token = _extract_auth_token(request)
    if not token:
        return None

    users = _get_table("api_auth_users")
    sessions = _get_table("api_auth_sessions")
    stmt = (
        select(
            users.c.id.label("id"),
            users.c.username.label("username"),
            users.c.is_staff.label("is_staff"),
            sessions.c.id.label("session_id"),
            sessions.c.expires_at.label("expires_at"),
        )
        .join(sessions, sessions.c.user_id == users.c.id)
        .where(sessions.c.token == token)
        .order_by(desc(sessions.c.id))
        .limit(1)
    )
    async with request.app.db.session as session:
        result = await session.execute(stmt)
        row = result.mappings().first()
        if row is None:
            return None
        if _is_expired(row.get("expires_at")):
            await session.execute(
                delete(sessions).where(sessions.c.id == row["session_id"])
            )
            await session.commit()
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "is_staff": bool(row["is_staff"]),
        }


async def _ensure_authenticated(request: web.Request) -> dict[str, Any]:
    user = await _get_authenticated_user(request)
    if user is not None:
        return user
    raise web.HTTPUnauthorized(
        text=json.dumps(
            {
                "error": "Authentication required",
                "hint": "Use POST /api/auth/login then pass Authorization: Bearer <token>",
            }
        ),
        content_type="application/json",
    )


async def _ensure_staff(request: web.Request) -> dict[str, Any]:
    user = await _ensure_authenticated(request)
    if user.get("is_staff"):
        return user
    raise web.HTTPForbidden(
        text=json.dumps({"error": "Admin access required"}),
        content_type="application/json",
    )


def _build_filters(table: Table, request: web.Request):
    filters = []
    for key, value in request.query.items():
        if key in RESERVED_QUERY_KEYS:
            continue
        column = table.columns.get(key)
        if column is None:
            continue
        filters.append(column == _coerce_value(column, value))
    return filters


def _build_openapi_spec(request: web.Request) -> dict[str, Any]:
    server_url = f"{request.scheme}://{request.host}"
    spec = APISpec(
        title="YorTrade Admin API",
        version="1.0.0",
        openapi_version="3.0.3",
        info={
            "description": "CRUD API with auth and role-based access over database tables."
        },
    )
    spec.components.security_scheme(
        "BearerAuth",
        {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "Token",
        },
    )

    def add_path(path: str, operations: dict[str, Any]) -> None:
        spec.path(path=path, operations=operations)

    add_path(
        "/api",
        {
            "get": {
                "summary": "API index",
                "responses": {"200": {"description": "Service index"}},
            }
        },
    )
    add_path(
        "/api/swagger",
        {
            "get": {
                "summary": "Swagger UI alias",
                "responses": {"302": {"description": "Redirect to OpenAPI JSON"}},
            }
        },
    )
    add_path(
        "/api/docs",
        {
            "get": {
                "summary": "Docs alias",
                "responses": {"302": {"description": "Redirect to OpenAPI JSON"}},
            }
        },
    )
    add_path(
        "/api/public",
        {
            "get": {
                "summary": "Public API entrypoint",
                "responses": {"200": {"description": "Public metadata"}},
            }
        },
    )
    add_path(
        "/api/health",
        {
            "get": {
                "summary": "Health check",
                "responses": {"200": {"description": "Service health"}},
            }
        },
    )
    add_path(
        "/api/auth/login",
        {
            "post": {
                "summary": "Login API user",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
                "responses": {"200": {"description": "Access token"}},
            }
        },
    )
    add_path(
        "/api/auth/logout",
        {
            "post": {
                "summary": "Logout current session",
                "security": [{"BearerAuth": []}],
                "responses": {"200": {"description": "Logged out"}},
            }
        },
    )
    add_path(
        "/api/tables",
        {
            "get": {
                "summary": "List available tables",
                "security": [{"BearerAuth": []}],
                "responses": {"200": {"description": "Table metadata"}},
            }
        },
    )
    add_path(
        "/api/{table}",
        {
            "get": {
                "summary": "List rows with filters",
                "security": [{"BearerAuth": []}],
                "parameters": [
                    {
                        "name": "table",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "offset",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "order_by",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "order_dir",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                    },
                ],
                "responses": {"200": {"description": "Rows list"}},
            },
            "post": {
                "summary": "Create row",
                "security": [{"BearerAuth": []}],
                "parameters": [
                    {
                        "name": "table",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
                "responses": {"201": {"description": "Created row"}},
            },
        },
    )
    add_path(
        "/api/{table}/{item_id}",
        {
            "get": {
                "summary": "Read row by single primary key",
                "security": [{"BearerAuth": []}],
                "parameters": [
                    {
                        "name": "table",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "item_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                ],
                "responses": {"200": {"description": "Row"}},
            },
            "patch": {
                "summary": "Update row by single primary key",
                "security": [{"BearerAuth": []}],
                "parameters": [
                    {
                        "name": "table",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "item_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                ],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
                "responses": {"200": {"description": "Updated row"}},
            },
            "delete": {
                "summary": "Delete row by single primary key",
                "security": [{"BearerAuth": []}],
                "parameters": [
                    {
                        "name": "table",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "item_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                ],
                "responses": {"200": {"description": "Deleted row"}},
            },
        },
    )
    add_path(
        "/api/{table}/clear",
        {
            "post": {
                "summary": "Delete many rows with optional query filters",
                "security": [{"BearerAuth": []}],
                "parameters": [
                    {
                        "name": "table",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "confirm",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                ],
                "responses": {"200": {"description": "Delete stats"}},
            }
        },
    )
    add_path(
        "/api/delete_user",
        {
            "get": {
                "summary": "Delete user by user_id or (platform + tg_user_id)",
                "security": [{"BearerAuth": []}],
                "parameters": [
                    {
                        "name": "user_id",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "tg_user_id",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "platform",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                    },
                ],
                "responses": {"200": {"description": "Deleted user"}},
            }
        },
    )

    result = spec.to_dict()
    result["servers"] = [{"url": server_url}]
    return result


async def login_api_user(request: web.Request) -> web.Response:
    body = await _read_json(request)
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if not username or not password:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "Fields 'username' and 'password' are required"}),
            content_type="application/json",
        )

    users = _get_table("api_auth_users")
    sessions = _get_table("api_auth_sessions")
    user_stmt = select(users).where(users.c.username == username)
    async with request.app.db.session as session:
        user_result = await session.execute(user_stmt)
        user_row = user_result.mappings().first()
        if not user_row or not _verify_password(
            password, str(user_row["password_hash"])
        ):
            raise web.HTTPUnauthorized(
                text=json.dumps({"error": "Invalid credentials"}),
                content_type="application/json",
            )

        ttl_hours = max(
            1, int(getattr(request.app.config, "API_AUTH_TTL_HOURS", 24) or 24)
        )
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        token = secrets.token_urlsafe(32)
        session_stmt = (
            insert(sessions)
            .values(
                user_id=user_row["id"],
                token=token,
                expires_at=expires_at,
            )
            .returning(sessions.c.id, sessions.c.expires_at)
        )
        session_result = await session.execute(session_stmt)
        created_session = session_result.mappings().first()
        await session.commit()

    return web.json_response(
        {
            "token": token,
            "token_type": "Bearer",
            "expires_at": _serialize_value(created_session["expires_at"])
            if created_session
            else None,
            "user": {
                "id": user_row["id"],
                "username": user_row["username"],
                "is_staff": bool(user_row["is_staff"]),
            },
        }
    )


async def logout_api_user(request: web.Request) -> web.Response:
    await _ensure_authenticated(request)
    token = _extract_auth_token(request)
    if token is None:
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": "Authentication required"}),
            content_type="application/json",
        )
    sessions = _get_table("api_auth_sessions")
    async with request.app.db.session as session:
        await session.execute(delete(sessions).where(sessions.c.token == token))
        await session.commit()
    return web.json_response({"status": "ok"})


async def openapi_json(request: web.Request) -> web.Response:
    return web.json_response(_build_openapi_spec(request))


async def swagger_ui(request: web.Request) -> web.Response:
    _ = request
    return web.HTTPFound(location="/api/openapi.json")


async def api_index(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "service": "admin_api",
            "routes": {
                "GET /api/openapi.json": "OpenAPI schema",
                "GET /api/docs": "Swagger UI",
                "GET /api/swagger": "Swagger UI alias",
                "GET /api/public": "Public metadata and links",
                "GET /api/health": "Public healthcheck",
                "POST /api/auth/login": "Get auth token",
                "POST /api/auth/logout": "Invalidate current token",
                "GET /api/tables": "Requires login",
                "GET /api/{table}": "Requires login",
                "GET /api/{table}/{id}": "Requires login",
                "POST /api/{table}": "Admin only",
                "PATCH /api/{table}/{id}": "Admin only",
                "DELETE /api/{table}/{id}": "Admin only",
                "POST /api/{table}/clear": "Admin only",
                "GET /api/delete_user?user_id=...": "Admin only",
                "GET /api/delete_user?tg_user_id=...&platform=TG|VK": "Admin only",
            },
        }
    )


async def public_info(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "service": "admin_api",
            "public_routes": {
                "GET /api": "API index",
                "GET /api/swagger": "Swagger UI alias",
                "GET /api/public": "Public metadata",
                "GET /api/health": "Healthcheck",
                "GET /api/openapi.json": "OpenAPI schema",
                "GET /api/docs": "Swagger UI",
                "POST /api/auth/login": "Login and get token",
            },
            "auth_header": "Authorization: Bearer <token>",
        }
    )


async def health(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "status": "ok",
            "now_utc": datetime.now(timezone.utc).isoformat(),
        }
    )


async def list_tables(request: web.Request) -> web.Response:
    await _ensure_authenticated(request)
    payload = [
        {
            "table": table.name,
            "primary_keys": [column.name for column in table.primary_key.columns],
            "columns": [column.name for column in table.columns],
        }
        for table in _available_tables().values()
    ]
    payload.sort(key=lambda item: item["table"])
    return web.json_response({"tables": payload})


async def read_rows(request: web.Request) -> web.Response:
    await _ensure_authenticated(request)
    table = _get_table(request.match_info["table"])
    limit = min(max(int(request.query.get("limit", "100")), 1), 1000)
    offset = max(int(request.query.get("offset", "0")), 0)
    order_by = request.query.get("order_by")
    order_dir = request.query.get("order_dir", "asc").lower()

    filters = _build_filters(table, request)
    stmt = select(table).where(*filters)
    if order_by and order_by in table.columns:
        order_column = table.columns[order_by]
        stmt = stmt.order_by(
            desc(order_column) if order_dir == "desc" else asc(order_column)
        )
    elif table.primary_key.columns:
        first_pk = next(iter(table.primary_key.columns))
        stmt = stmt.order_by(asc(first_pk))
    stmt = stmt.limit(limit).offset(offset)

    count_stmt = select(func.count()).select_from(table).where(*filters)
    async with request.app.db.session as session:
        rows_result = await session.execute(stmt)
        count_result = await session.execute(count_stmt)
        rows = [_serialize_row(dict(row)) for row in rows_result.mappings().all()]
        total = int(count_result.scalar_one())

    return web.json_response(
        {
            "table": table.name,
            "total": total,
            "limit": limit,
            "offset": offset,
            "count": len(rows),
            "rows": rows,
        }
    )


async def read_row_by_id(request: web.Request) -> web.Response:
    await _ensure_authenticated(request)
    table = _get_table(request.match_info["table"])
    pk = _single_pk_column(table)
    raw_id = request.match_info["item_id"]
    pk_value = _coerce_value(pk, raw_id)
    stmt = select(table).where(pk == pk_value)

    async with request.app.db.session as session:
        result = await session.execute(stmt)
        row = result.mappings().first()

    if row is None:
        raise web.HTTPNotFound(
            text=json.dumps(
                {"error": f"Row not found in '{table.name}' for {pk.name}={raw_id}"}
            ),
            content_type="application/json",
        )
    return web.json_response({"table": table.name, "row": _serialize_row(dict(row))})


async def create_row(request: web.Request) -> web.Response:
    await _ensure_staff(request)
    table = _get_table(request.match_info["table"])
    body = await _read_json(request)
    values = {}

    for key, value in body.items():
        column = table.columns.get(key)
        if column is None:
            continue
        values[key] = _coerce_value(column, value)

    if not values:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "No valid fields provided"}),
            content_type="application/json",
        )

    stmt = insert(table).values(**values).returning(table)
    try:
        async with request.app.db.session as session:
            result = await session.execute(stmt)
            await session.commit()
            row = result.mappings().first()
    except SQLAlchemyError as exc:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": f"Create failed: {exc}"}),
            content_type="application/json",
        ) from exc

    return web.json_response(
        {"table": table.name, "created": _serialize_row(dict(row)) if row else None},
        status=201,
    )


async def update_row_by_id(request: web.Request) -> web.Response:
    await _ensure_staff(request)
    table = _get_table(request.match_info["table"])
    pk = _single_pk_column(table)
    raw_id = request.match_info["item_id"]
    pk_value = _coerce_value(pk, raw_id)
    body = await _read_json(request)
    values = {}

    for key, value in body.items():
        column = table.columns.get(key)
        if column is None or column.primary_key:
            continue
        values[key] = _coerce_value(column, value)

    if not values:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "No updatable fields provided"}),
            content_type="application/json",
        )

    stmt = update(table).where(pk == pk_value).values(**values).returning(table)
    try:
        async with request.app.db.session as session:
            result = await session.execute(stmt)
            await session.commit()
            row = result.mappings().first()
    except SQLAlchemyError as exc:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": f"Update failed: {exc}"}),
            content_type="application/json",
        ) from exc

    if row is None:
        raise web.HTTPNotFound(
            text=json.dumps(
                {"error": f"Row not found in '{table.name}' for {pk.name}={raw_id}"}
            ),
            content_type="application/json",
        )
    return web.json_response(
        {"table": table.name, "updated": _serialize_row(dict(row))}
    )


async def delete_row_by_id(request: web.Request) -> web.Response:
    await _ensure_staff(request)
    table = _get_table(request.match_info["table"])
    pk = _single_pk_column(table)
    raw_id = request.match_info["item_id"]
    pk_value = _coerce_value(pk, raw_id)

    stmt = delete(table).where(pk == pk_value).returning(pk)
    try:
        async with request.app.db.session as session:
            result = await session.execute(stmt)
            await session.commit()
            deleted = result.scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": f"Delete failed: {exc}"}),
            content_type="application/json",
        ) from exc

    if deleted is None:
        raise web.HTTPNotFound(
            text=json.dumps(
                {"error": f"Row not found in '{table.name}' for {pk.name}={raw_id}"}
            ),
            content_type="application/json",
        )
    return web.json_response({"table": table.name, "deleted": {pk.name: deleted}})


async def clear_table(request: web.Request) -> web.Response:
    await _ensure_staff(request)
    table = _get_table(request.match_info["table"])
    confirm = request.query.get("confirm", "").lower()
    if confirm not in {"yes", "true", "1"}:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "Pass ?confirm=yes to clear data"}),
            content_type="application/json",
        )

    filters = _build_filters(table, request)
    stmt = delete(table).where(*filters)
    try:
        async with request.app.db.session as session:
            result = await session.execute(stmt)
            await session.commit()
            deleted_count = int(result.rowcount or 0)
    except SQLAlchemyError as exc:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": f"Clear failed: {exc}"}),
            content_type="application/json",
        ) from exc

    return web.json_response({"table": table.name, "deleted_count": deleted_count})


async def delete_user_legacy(request: web.Request) -> web.Response:
    await _ensure_staff(request)
    table = _get_table("users")
    user_id = request.query.get("user_id")
    tg_user_id = request.query.get("tg_user_id")
    platform = request.query.get("platform")
    if not user_id and not tg_user_id:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "Pass user_id or tg_user_id"}),
            content_type="application/json",
        )
    if tg_user_id and not user_id and not platform:
        raise web.HTTPBadRequest(
            text=json.dumps(
                {
                    "error": "Pass platform together with tg_user_id (e.g. platform=TG or platform=VK)"
                }
            ),
            content_type="application/json",
        )

    filters = []
    if user_id:
        filters.append(table.c.id == _coerce_value(table.c.id, user_id))
    if tg_user_id:
        filters.append(
            table.c.tg_user_id == _coerce_value(table.c.tg_user_id, tg_user_id)
        )
    if platform:
        filters.append(table.c.platform == str(platform).upper())
    stmt = (
        delete(table)
        .where(*filters)
        .returning(table.c.id, table.c.tg_user_id, table.c.platform)
    )
    try:
        async with request.app.db.session as session:
            result = await session.execute(stmt)
            await session.commit()
            deleted_row = result.mappings().first()
    except SQLAlchemyError as exc:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": f"Delete user failed: {exc}"}),
            content_type="application/json",
        ) from exc

    if deleted_row is None:
        raise web.HTTPNotFound(
            text=json.dumps({"error": "User not found"}),
            content_type="application/json",
        )
    return web.json_response({"deleted_user": _serialize_row(dict(deleted_row))})


def setup_admin_api(app: web.Application) -> None:
    app.router.add_get("/api/openapi.json", openapi_json)
    app.router.add_get("/api/docs", swagger_ui)
    app.router.add_get("/api/swagger", swagger_ui)
    app.router.add_get("/api", api_index)
    app.router.add_get("/api/public", public_info)
    app.router.add_get("/api/health", health)
    app.router.add_post("/api/auth/login", login_api_user)
    app.router.add_post("/api/auth/logout", logout_api_user)
    app.router.add_get("/api/tables", list_tables)
    app.router.add_get("/api/delete_user", delete_user_legacy)
    app.router.add_post("/api/{table}/clear", clear_table)
    app.router.add_get("/api/{table}/{item_id}", read_row_by_id)
    app.router.add_patch("/api/{table}/{item_id}", update_row_by_id)
    app.router.add_delete("/api/{table}/{item_id}", delete_row_by_id)
    app.router.add_get("/api/{table}", read_rows)
    app.router.add_post("/api/{table}", create_row)
