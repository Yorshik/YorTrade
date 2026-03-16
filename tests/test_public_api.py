import asyncio
import json
from types import SimpleNamespace

from aiohttp import web

from app.api import admin


def _request():
    return SimpleNamespace(
        query={},
        headers={},
        app=SimpleNamespace(config=SimpleNamespace()),
    )


def test_public_info_available_without_auth() -> None:
    response = asyncio.run(admin.public_info(_request()))
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["service"] == "admin_api"
    assert "GET /api/docs" in payload["public_routes"]


def test_health_available_without_auth() -> None:
    response = asyncio.run(admin.health(_request()))
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["status"] == "ok"
    assert "now_utc" in payload


def test_setup_registers_swagger_alias_route() -> None:
    app_obj = web.Application()
    admin.setup_admin_api(app_obj)
    paths = {route.resource.canonical for route in app_obj.router.routes()}

    assert "/api/swagger" in paths
    assert "/api/auth/register" not in paths


def test_swagger_alias_redirects_to_openapi_json() -> None:
    response = asyncio.run(admin.swagger_ui(_request()))

    assert response.status == 302
    assert response.headers.get("Location") == "/api/openapi.json"
