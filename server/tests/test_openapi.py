import pytest
from fastapi.testclient import TestClient
import os
import sys

# Add src to python path so we can import main
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.main import app

client = TestClient(app)

def test_openapi_json_is_served():
    """Ensure that the OpenAPI schema is available at /openapi.json."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "openapi" in data
    assert "info" in data
    assert data["info"]["title"] == "Joplin Server Vector Memory API"

def test_fastapi_docs_are_enabled():
    """Ensure built-in FastAPI documentation endpoints are enabled at /docs."""
    response_docs = client.get("/docs")
    assert response_docs.status_code == 200
    
    response_redoc = client.get("/redoc")
    assert response_redoc.status_code == 404

def test_openapi_contains_workflow_links_and_examples():
    """Ensure that the OpenAPI schema contains links and workflow examples."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    
    # Check for links in Search endpoint
    search_responses = data["paths"]["/http-api/search"]["post"]["responses"]
    assert "links" in search_responses["200"]
    assert "GetNoteById" in search_responses["200"]["links"]
    assert "RequestDeletionById" in search_responses["200"]["links"]
    assert search_responses["200"]["links"]["GetNoteById"]["operationId"] == "api_get_http_api_get_post"

    # Check for links in Remember endpoint
    remember_responses = data["paths"]["/http-api/remember"]["post"]["responses"]
    assert "links" in remember_responses["200"]
    assert "GetNoteById" in remember_responses["200"]["links"]
    assert "RequestDeletionById" in remember_responses["200"]["links"]    
    # Check for examples in Pydantic models
    schemas = data["components"]["schemas"]
    assert "SearchRequest" in schemas
    assert "examples" in schemas["SearchRequest"]["properties"]["query"]
    assert schemas["SearchRequest"]["properties"]["query"]["examples"] == ["how to cook pasta"]
    
    assert "SearchResponseItem" in schemas
    assert "examples" in schemas["SearchResponseItem"]["properties"]["title"]
    
    assert "GetResponse" in schemas
    assert "examples" in schemas["GetResponse"]["properties"]["content"]
