"""
Unit tests for FastMCP resource tools:
- get_resource (lines 672-706): text types, images (ImageContent), binary blobs (EmbeddedResource), non-200, exceptions
- upload_resource (lines 708-767): images (markdown ! prefix), docs, node proxy errors, exceptions
"""
import os
import sys
import json
import base64
import pytest
from unittest.mock import patch, MagicMock
from mcp.types import ImageContent, EmbeddedResource, TextContent

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.main import get_resource, upload_resource  # noqa: E402


@pytest.fixture(autouse=True)
def override_proxy_fixture():
    """Ensure clean proxy mocking per test."""
    with patch("src.main._call_node_proxy") as mock:
        yield mock


def test_get_resource_text_types(override_proxy_fixture):
    """Text-based content types should return plain string text."""
    test_cases = [
        ("text/plain", "Hello world text"),
        ("text/markdown", "# Header\nContent"),
        ("application/json", '{"key": "value"}'),
        ("application/x-sh", "#!/bin/bash\necho 1"),
        ("application/javascript", 'console.log("hi");'),
    ]
    for mime, body in test_cases:
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"Content-Type": mime}
        resp.text = body
        override_proxy_fixture.return_value = resp

        result = get_resource("res_text_id")
        assert result == body


def test_get_resource_image_types(override_proxy_fixture):
    """Image types should return ImageContent with valid base64 data."""
    raw_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    expected_b64 = base64.b64encode(raw_bytes).decode("utf-8")

    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "image/png"}
    resp.content = raw_bytes
    override_proxy_fixture.return_value = resp

    result = get_resource("res_img_id")
    assert isinstance(result, ImageContent)
    assert result.type == "image"
    assert result.mimeType == "image/png"
    assert result.data == expected_b64


def test_get_resource_binary_blob(override_proxy_fixture):
    """Non-text, non-image types should return EmbeddedResource with BlobResourceContents."""
    raw_pdf = b"%PDF-1.4 header..."
    expected_b64 = base64.b64encode(raw_pdf).decode("utf-8")

    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "application/pdf"}
    resp.content = raw_pdf
    override_proxy_fixture.return_value = resp

    result = get_resource("res_pdf_id")
    assert isinstance(result, EmbeddedResource)
    assert result.type == "resource"
    assert result.resource.mimeType == "application/pdf"
    assert result.resource.blob == expected_b64
    assert str(result.resource.uri) == "joplin://resource/res_pdf_id"


def test_get_resource_proxy_error(override_proxy_fixture):
    """Non-200 responses return descriptive error text."""
    resp = MagicMock()
    resp.status_code = 404
    resp.text = "Resource not found on node proxy"
    override_proxy_fixture.return_value = resp

    result = get_resource("missing_res")
    assert result == "Error fetching resource: Resource not found on node proxy"


def test_get_resource_exception(override_proxy_fixture):
    """Network or proxy exceptions are caught and formatted."""
    override_proxy_fixture.side_effect = ConnectionError("Node proxy connection refused")
    result = get_resource("err_res")
    assert "Error: Node proxy connection refused" in result


def test_upload_resource_image_success(override_proxy_fixture):
    """Uploading an image generates markdown link with leading exclamation mark (!)."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"id": "img123"}
    override_proxy_fixture.return_value = resp

    result = upload_resource("photo.png", "base64data", mime_type="image/png")
    assert len(result) == 2
    assert all(isinstance(x, TextContent) for x in result)

    assistant_msg = json.loads(result[0].text)
    assert assistant_msg["resource_id"] == "img123"
    assert assistant_msg["markdown_link"] == "![photo.png](:/img123)"
    assert "photo.png" in result[1].text


def test_upload_resource_document_success(override_proxy_fixture):
    """Uploading a document generates standard markdown link without exclamation mark."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"id": "doc456"}
    override_proxy_fixture.return_value = resp

    result = upload_resource("manual.pdf", "base64data", mime_type="application/pdf")
    assistant_msg = json.loads(result[0].text)
    assert assistant_msg["resource_id"] == "doc456"
    assert assistant_msg["markdown_link"] == "[manual.pdf](:/doc456)"


def test_upload_resource_no_mime_type(override_proxy_fixture):
    """Uploading without explicit mime_type defaults to standard link."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"id": "bin789"}
    override_proxy_fixture.return_value = resp

    result = upload_resource("archive.tar", "base64data")
    assistant_msg = json.loads(result[0].text)
    assert assistant_msg["markdown_link"] == "[archive.tar](:/bin789)"


def test_upload_resource_proxy_error(override_proxy_fixture):
    """Proxy returning error status returns assistant and user error contents."""
    resp = MagicMock()
    resp.status_code = 500
    resp.text = "Internal node proxy upload failure"
    override_proxy_fixture.return_value = resp

    result = upload_resource("bad.txt", "data")
    assert len(result) == 2
    assistant_msg = json.loads(result[0].text)
    assert "Error uploading resource: Internal node proxy upload failure" in assistant_msg["error"]
    assert "Error uploading resource: Internal node proxy upload failure" in result[1].text


def test_upload_resource_exception(override_proxy_fixture):
    """Exception during upload caught gracefully."""
    override_proxy_fixture.side_effect = TimeoutError("Upload timed out")
    result = upload_resource("file.dat", "data")
    assert len(result) == 2
    assistant_msg = json.loads(result[0].text)
    assert "Upload timed out" in assistant_msg["error"]
    assert "Upload timed out" in result[1].text
