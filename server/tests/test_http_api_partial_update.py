import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_http_api_partial_replacement_flow(client, temp_config_and_db, mock_ollama):
    """
    Test HTTP API endpoint POST /http-api/update with partial note replacement:
    - Unique replacement
    - Ambiguous replacement (HTTP 400 with detail)
    - Search text not found (HTTP 400 with detail)
    - Replace text too long (HTTP 400 with detail)
    - Stale OCC timestamp (HTTP 409)
    - Backward compatibility: full note replacement without search_text
    """
    _, _, token = temp_config_and_db
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create a test note
    create_res = client.post(
        "/http-api/remember",
        json={
            "title": "Machine Spec",
            "content": "There is a computer who is a computer",
        },
        headers=headers,
    )
    assert create_res.status_code == 200
    note_id = create_res.json()["id"]

    # 2. Get current updated_time
    get_res = client.post("/http-api/get", json={"note_id": note_id}, headers=headers)
    assert get_res.status_code == 200
    timestamp = get_res.json()["updated_time"]

    with patch("src.main._call_node_proxy") as mock_proxy:
        mock_proxy.return_value.status_code = 200
        mock_proxy.return_value.json.return_value = {"status": "success"}

        # 3. Successful partial update using the exact JSON format from prompt
        update_payload = {
            "note_id": note_id,
            "content": "boy who",
            "search_text": "computer who",
            "update_mode": "full note replacement",
            "last_modified_timestamp": timestamp,
            "summary_of_changes": "Replace computer who with boy who",
        }
        res = client.post("/http-api/update", json=update_payload, headers=headers)
        assert res.status_code == 200
        assert res.json().get("status") == "success"

        # Verify proxy call received transformed body
        mock_proxy.assert_called_once()
        call_args = mock_proxy.call_args
        assert call_args[0][0] == "PUT"
        assert call_args[0][1] == f"/node-api/notes/{note_id}"
        assert call_args[1]["json_data"]["body"] == "There is a boy who is a computer"

        # Verify updated note via /http-api/get
        verify_res = client.post("/http-api/get", json={"note_id": note_id}, headers=headers)
        assert verify_res.status_code == 200
        assert verify_res.json()["content"] == "There is a boy who is a computer"
        new_timestamp = verify_res.json()["updated_time"]
        assert new_timestamp > timestamp

        # 4. Ambiguous match returns HTTP 400
        bad_ambiguous = {
            "note_id": note_id,
            "content": "dog",
            "search_text": "computer",
            "update_mode": "partial note replacement",
            "last_modified_timestamp": new_timestamp,
            "summary_of_changes": "Try ambiguous search",
        }
        # In 'There is a boy who is a computer', 'is a' appears twice
        bad_ambiguous["search_text"] = "is a"
        res_ambiguous = client.post("/http-api/update", json=bad_ambiguous, headers=headers)
        assert res_ambiguous.status_code == 400
        assert "multiple instances of `is a` found" in res_ambiguous.json()["detail"]

        # 5. Search text not found returns HTTP 400
        bad_not_found = {
            "note_id": note_id,
            "content": "Foobar",
            "search_text": "Doggy",
            "update_mode": "partial note replacement",
            "last_modified_timestamp": new_timestamp,
            "summary_of_changes": "Try not found",
        }
        res_not_found = client.post("/http-api/update", json=bad_not_found, headers=headers)
        assert res_not_found.status_code == 400
        assert res_not_found.json()["detail"] == "search text not found"

        # 6. Replace text too long returns HTTP 400
        bad_too_long = {
            "note_id": note_id,
            "content": "foo",
            "search_text": "x" * 1_000_000,
            "update_mode": "partial note replacement",
            "last_modified_timestamp": new_timestamp,
            "summary_of_changes": "Try oversized",
        }
        res_too_long = client.post("/http-api/update", json=bad_too_long, headers=headers)
        assert res_too_long.status_code == 400
        assert res_too_long.json()["detail"] == "replace text too long"

        # 7. OCC timestamp mismatch returns HTTP 409
        bad_occ = {
            "note_id": note_id,
            "content": "something",
            "search_text": "boy",
            "update_mode": "partial note replacement",
            "last_modified_timestamp": timestamp,  # Stale timestamp!
            "summary_of_changes": "OCC conflict test",
        }
        res_occ = client.post("/http-api/update", json=bad_occ, headers=headers)
        assert res_occ.status_code == 409
        assert "modified since you last read it" in res_occ.json()["detail"]

        # 8. Note not found returns HTTP 404
        bad_id = {
            "note_id": "nonexistent-note-id",
            "content": "something",
            "search_text": "boy",
            "update_mode": "partial note replacement",
            "last_modified_timestamp": new_timestamp,
            "summary_of_changes": "Missing note",
        }
        res_missing = client.post("/http-api/update", json=bad_id, headers=headers)
        assert res_missing.status_code == 404
        assert res_missing.json()["detail"] == "Note not found"

        # 9. Backward compatibility: full note replacement without search_text
        full_replace_payload = {
            "note_id": note_id,
            "content": "Brand new note content.",
            "update_mode": "full note replacement",
            "last_modified_timestamp": new_timestamp,
            "summary_of_changes": "Full replacement test",
        }
        res_full = client.post("/http-api/update", json=full_replace_payload, headers=headers)
        assert res_full.status_code == 200
        verify_full = client.post("/http-api/get", json={"note_id": note_id}, headers=headers)
        assert verify_full.json()["content"] == "Brand new note content."
