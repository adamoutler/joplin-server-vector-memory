from src.main import search_notes, get_note, remember, request_note_deletion, execute_deletion, update_note
import pytest
import os
import sys
import tempfile
from unittest.mock import patch

# Add src to python path so we can import main and db
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture
def temp_db():
    # Create a temporary file for the database
    fd, path = tempfile.mkstemp()
    os.environ["SQLITE_DB_PATH"] = path

    yield path

    # Clean up
    os.close(fd)
    os.remove(path)


@pytest.fixture
def mock_ollama():
    with patch('src.main.get_embedding') as mock_embed:
        # Return a simple mock embedding of 384 zeros
        # We can modify a specific index based on the prompt for testing
        def side_effect(text):
            vec = [0.0] * 768
            if "test query" in text.lower():
                vec[0] = 1.0
            elif "apple" in text.lower():
                vec[1] = 1.0
            else:
                vec[2] = 1.0
            return vec

        mock_embed.side_effect = side_effect
        yield mock_embed


def test_remember_and_get_note(temp_db, mock_ollama):
    # Remember a note
    result = remember("Apple Recipe", "How to make apple pie")
    assert result.get("status") == "success"
    note_id = result.get("id")
    assert note_id is not None

    # Get the note
    note = get_note(note_id)
    assert note.get("id") == note_id
    assert note.get("title") == "[Agent Memory] Apple Recipe"
    assert note.get("content") == "How to make apple pie"


def test_search_notes(temp_db, mock_ollama):
    # Add a few notes
    remember("Apple Pie", "Delicious apple pie recipe")
    remember("Banana Bread", "Easy banana bread recipe")

    # Add a large note to test blurb truncation
    large_content = "x" * 2500
    remember("Large Note", large_content)

    # Search for something that will match apple pie better based on mock
    # Our mock makes "test query" vector have vec[0]=1.0
    # "Apple" has vec[1]=1.0
    # "Banana" has vec[2]=1.0
    # Let's adjust mock logic or just test it returns something
    results = search_notes("apple query")
    assert len(results) == 3

    # Results should contain blurb, title, id
    assert "blurb" in results[0]
    assert "id" in results[0]
    assert "title" in results[0]

    # Top result should contain full_body
    assert "full_body" in results[0]
    assert results[0]["full_body"] is not None

    # Second result should NOT contain full_body
    if len(results) > 1:
        assert "full_body" not in results[1]

    # Verify blurb truncation
    large_note_result = next(r for r in results if r["title"] == "[Agent Memory] Large Note")
    assert len(large_note_result["blurb"]) == 2003
    assert large_note_result["blurb"].endswith("...")


def test_delete_note_flow(temp_db, mock_ollama):
    # Add a note
    result = remember("To be deleted", "Delete this content")
    note_id = result.get("id")

    # Verify it exists and get hash
    note = get_note(note_id)
    assert note.get("id") == note_id
    content_hash = note.get("content_hash")

    # Request deletion
    req_result = request_note_deletion(note_id, "Test deletion")
    assert "deletion_token" in req_result
    token = req_result["deletion_token"]

    # Execute deletion
    attestation = {
        "content_hash": content_hash,
        "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
    }
    exec_result = execute_deletion(token, "[Agent Memory] To be deleted", attestation)
    assert exec_result.get("status") == "success"

    # Verify it's gone
    note_after = get_note(note_id)
    assert note_after.get("error") == "Note not found"


def test_delete_nonexistent_note(temp_db):
    result = request_note_deletion("nonexistent_id", "Test")
    assert result.get("error") == "Note not found"


def test_get_nonexistent_note(temp_db):
    result = get_note("nonexistent_id")
    assert result.get("error") == "Note not found"


def test_update_note_success(temp_db, mock_ollama):
    # Remember a note
    result = remember("Update Test", "Initial content")
    assert result.get("status") == "success"
    note_id = result.get("id")

    # Get the note and its timestamp
    note = get_note(note_id)
    timestamp = note.get("updated_time")
    assert timestamp is not None

    # Update the note (append)
    update_res = update_note(note_id, "Appended content", "append", timestamp, "Test append")
    assert update_res.get("status") == "success"

    # Verify the update
    updated_note = get_note(note_id)
    assert "Appended content" in updated_note.get("content")
    assert updated_note.get("updated_time") >= timestamp


def test_update_note_occ_failure(temp_db, mock_ollama):
    # Remember a note
    result = remember("OCC Test", "Initial content")
    note_id = result.get("id")

    # Get the note to get initial timestamp
    note = get_note(note_id)
    initial_timestamp = note.get("updated_time")

    # Provide a wrong/stale timestamp
    stale_timestamp = initial_timestamp - 1000

    # Update should fail
    update_res = update_note(note_id, "This should fail", "full note replacement", stale_timestamp, "Test OCC")
    assert update_res.get(
        "error") == "Error: Note has been modified since you last read it. Retrieve the note again before updating."


def test_config_caching():
    from src.main import get_config, verify_token
    import src.main as main_module
    import time
    import json
    from fastapi.security import HTTPAuthorizationCredentials

    # Reset cache for testing
    main_module._config_cache = {}
    main_module._config_mtime = 0

    fd, path = tempfile.mkstemp()
    with open(path, "w") as f:
        json.dump({"token": "test-token", "embedding": {"provider": "ollama", "baseUrl": "http://test-url", "model": "test-model"}}, f)

    os.environ["CONFIG_PATH"] = path

    # First call, should read from file
    with patch("builtins.open", side_effect=open) as mock_open:
        config1 = get_config()
        assert config1["embedding"]["baseUrl"] == "http://test-url"
        assert mock_open.call_count >= 1
        initial_call_count = mock_open.call_count

        # Second call, should use cache
        config2 = get_config()
        assert mock_open.call_count == initial_call_count

    # Modify the file and its modification time
    new_time = time.time() + 10
    with open(path, "w") as f:
        json.dump({"api_keys": [{"key": "new-token"}],
                  "embedding": {"provider": "ollama", "baseUrl": "http://new-url", "model": "test-model"}}, f)
    os.utime(path, (new_time, new_time))

    with patch("builtins.open", side_effect=open) as mock_open:
        # Third call, should reload because mtime changed
        config3 = get_config()
        assert config3["embedding"]["baseUrl"] == "http://new-url"
        assert mock_open.call_count >= 1
        reload_call_count = mock_open.call_count

        # Check verify_token uses the same cache
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="new-token")
        token = verify_token(creds)
        assert token == "new-token"
        assert mock_open.call_count == reload_call_count  # No new reads

    os.close(fd)
    os.remove(path)
