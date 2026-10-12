import pytest
import httpx
from starlette.testclient import TestClient
from unittest.mock import AsyncMock, patch
from src.main import _fastapi_app


@pytest.fixture
def client():
    # Use _fastapi_app directly with TestClient to invoke ASGI lifespan and routes
    with TestClient(_fastapi_app, base_url="http://192.168.1.101:30800") as test_client:
        yield test_client


def test_proxy_well_known_oauth_discovery(client):
    mock_resp = httpx.Response(
        status_code=200,
        json={
            "issuer": "http://192.168.1.101:30800",
            "authorization_endpoint": "http://192.168.1.101:30800/oauth/authorize",
            "token_endpoint": "http://192.168.1.101:30800/oauth/token",
        },
        headers={"content-type": "application/json"},
    )

    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp
        response = client.get(
            "/.well-known/oauth-authorization-server",
            headers={"Host": "192.168.1.101:30800"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["issuer"] == "http://192.168.1.101:30800"
        mock_req.assert_called_once()
        call_kwargs = mock_req.call_args.kwargs
        assert call_kwargs["headers"]["x-forwarded-host"] == "192.168.1.101:30800"


def test_proxy_well_known_openid_configuration(client):
    mock_resp = httpx.Response(
        status_code=200,
        json={"issuer": "http://192.168.1.101:30800"},
        headers={"content-type": "application/json"},
    )

    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp
        response = client.get("/.well-known/openid-configuration")
        assert response.status_code == 200
        # Target url must map to oauth-authorization-server
        assert (
            mock_req.call_args.kwargs["url"]
            == "http://127.0.0.1:3000/.well-known/oauth-authorization-server"
        )


def test_proxy_oauth_authorize_get_redirect(client):
    mock_resp = httpx.Response(
        status_code=302,
        headers={"location": "/authorize.html?request_id=req_123"},
    )

    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp
        response = client.get(
            "/oauth/authorize?client_id=gemini&response_type=code",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/authorize.html?request_id=req_123"


def test_proxy_oauth_authorize_internal_location_rewrite(client):
    mock_resp = httpx.Response(
        status_code=302,
        headers={
            "location": "http://127.0.0.1:3000/authorize.html?request_id=req_abc"
        },
    )

    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp
        response = client.get(
            "/oauth/authorize?client_id=gemini",
            headers={
                "Host": "192.168.1.101:30800",
                "X-Forwarded-Proto": "https",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        # Must be rewritten to external origin
        assert (
            response.headers["location"]
            == "https://192.168.1.101:30800/authorize.html?request_id=req_abc"
        )


def test_proxy_oauth_authorize_post(client):
    mock_resp = httpx.Response(
        status_code=302,
        headers={"location": "https://client.com/callback?code=jms_code_123"},
    )

    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp
        response = client.post(
            "/oauth/authorize",
            data={"request_id": "req_123", "shared_secret": "my-secret"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert (
            response.headers["location"]
            == "https://client.com/callback?code=jms_code_123"
        )


def test_proxy_oauth_token_exchange(client):
    mock_resp = httpx.Response(
        status_code=200,
        json={
            "access_token": "JMS_testtoken123",
            "token_type": "Bearer",
            "expires_in": 31536000,
        },
        headers={"content-type": "application/json"},
    )

    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp
        response = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": "jms_code_123",
                "client_id": "gemini",
            },
        )
        assert response.status_code == 200
        assert response.json()["access_token"] == "JMS_testtoken123"


def test_proxy_authorize_html(client):
    mock_resp = httpx.Response(
        status_code=200,
        text="<!DOCTYPE html><html><body>Consent Page</body></html>",
        headers={"content-type": "text/html"},
    )

    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp
        response = client.get("/authorize.html?request_id=req_123")
        assert response.status_code == 200
        assert "Consent Page" in response.text


def test_proxy_oauth_requests_details_and_status(client):
    mock_details = httpx.Response(
        status_code=200,
        json={"client_id": "gemini", "user_code": "AB12-CD34"},
        headers={"content-type": "application/json"},
    )
    mock_status = httpx.Response(
        status_code=200,
        json={"status": "pending"},
        headers={"content-type": "application/json"},
    )

    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_details
        res1 = client.get("/oauth/requests/req_abcdef1234567890/details")
        assert res1.status_code == 200
        assert res1.json()["client_id"] == "gemini"

        mock_req.return_value = mock_status
        res2 = client.get("/oauth/requests/req_abcdef1234567890/status")
        assert res2.status_code == 200
        assert res2.json()["status"] == "pending"


def test_proxy_disallowed_paths_return_404(client):
    # Attempting to access admin or internal paths through proxy
    res1 = client.get("/oauth/requests/invalid_id/secrets")
    assert res1.status_code == 404

    res2 = client.get("/.well-known/security.txt")
    assert res2.status_code == 404

    res3 = client.get("/oauth/../auth/wipe")
    assert res3.status_code == 404


def test_proxy_node_backend_unavailable_503(client):
    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = httpx.ConnectError("Connection refused")
        response = client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 503
        data = response.json()
        assert data["error"] == "temporarily_unavailable"
