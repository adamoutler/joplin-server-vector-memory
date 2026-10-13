import pytest
import os
import sys
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.main import app, mcp  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


def test_mcp_server_info_contains_icons():
    """Verify that FastMCP serverInfo includes icons per SEP-973."""
    assert hasattr(mcp, "icons")
    assert mcp.icons is not None
    assert len(mcp.icons) >= 1
    # Check that at least one icon provides a data URI or valid image source
    icon_srcs = [i.src for i in mcp.icons]
    assert any(src.startswith("data:image/png;base64,") for src in icon_srcs)
    assert any(src == "/icon.png" for src in icon_srcs)


def test_get_favicon_ico(client):
    """Verify GET /favicon.ico returns 200 and image/x-icon."""
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "image/x-icon"
    assert response.headers.get("access-control-allow-origin") == "*"
    assert len(response.content) > 0


def test_get_icon_png(client):
    """Verify GET /icon.png returns 200 and image/png."""
    response = client.get("/icon.png")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "image/png"
    assert response.headers.get("access-control-allow-origin") == "*"
    assert len(response.content) > 0


def test_get_icon_svg(client):
    """Verify GET /icon.svg returns 200 and image/svg+xml."""
    response = client.get("/icon.svg")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "image/svg+xml"
    assert response.headers.get("access-control-allow-origin") == "*"
    assert b"<svg" in response.content


def test_get_apple_touch_icon(client):
    """Verify GET /apple-touch-icon.png returns 200 and image/png."""
    response = client.get("/apple-touch-icon.png")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "image/png"
    assert response.headers.get("access-control-allow-origin") == "*"
    assert len(response.content) > 0


def test_get_manifest_json(client):
    """Verify GET /manifest.json returns 200 and valid JSON."""
    response = client.get("/manifest.json")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/json"
    data = response.json()
    assert data["name"] == "Joplin Server Vector Memory"
    assert len(data["icons"]) >= 2
