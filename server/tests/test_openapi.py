from src.main import app
from fastapi.testclient import TestClient
import os
import sys

# Add src to python path so we can import main
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

client = TestClient(app)


def test_openapi_json_is_enabled():
    """Ensure that the OpenAPI schema is enabled at /openapi.json."""
    response = client.get("/openapi.json")
    assert response.status_code == 200


def test_fastapi_docs_are_enabled():
    """Ensure built-in FastAPI documentation endpoints are enabled at /docs and /redoc."""
    response_docs = client.get("/docs")
    assert response_docs.status_code == 200

    response_redoc = client.get("/redoc")
    assert response_redoc.status_code == 200
