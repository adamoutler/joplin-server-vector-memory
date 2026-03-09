import pytest
import os
import sys
import tempfile
from unittest.mock import patch
import json

# Add src to python path so we can import main and db
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.main import search_notes, get_note, remember, delete_note

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
        # Return a simple mock embedding of 768 zeros
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

    # Verify blurb truncation
    large_note_result = next(r for r in results if r["title"] == "[Agent Memory] Large Note")
    assert len(large_note_result["blurb"]) == 2003
    assert large_note_result["blurb"].endswith("...")
    assert "title" in results[0]

def test_delete_note(temp_db, mock_ollama):
    # Add a note
    result = remember("To be deleted", "Delete this content")
    note_id = result.get("id")
    
    # Verify it exists
    note = get_note(note_id)
    assert note.get("id") == note_id
    
    # Delete it
    del_result = delete_note(note_id)
    assert del_result.get("status") == "success"
    
    # Verify it's gone
    note_after = get_note(note_id)
    assert note_after.get("error") == "Note not found"

def test_delete_nonexistent_note(temp_db):
    result = delete_note("nonexistent_id")
    assert result.get("error") == "Note not found"

def test_get_nonexistent_note(temp_db):
    result = get_note("nonexistent_id")
    assert result.get("error") == "Note not found"

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
        json.dump({"token": "test-token", "ollamaUrl": "http://test-url", "embeddingModel": "test-model"}, f)
    
    os.environ["CONFIG_PATH"] = path
    
    # First call, should read from file
    with patch("builtins.open", side_effect=open) as mock_open:
        config1 = get_config()
        assert config1["ollama_url"] == "http://test-url"
        assert mock_open.call_count >= 1
        initial_call_count = mock_open.call_count
        
        # Second call, should use cache
        config2 = get_config()
        assert mock_open.call_count == initial_call_count
        
    # Modify the file and its modification time
    new_time = time.time() + 10
    with open(path, "w") as f:
        json.dump({"token": "new-token", "ollamaUrl": "http://new-url", "embeddingModel": "test-model"}, f)
    os.utime(path, (new_time, new_time))
            
    with patch("builtins.open", side_effect=open) as mock_open:
        # Third call, should reload because mtime changed
        config3 = get_config()
        assert config3["ollama_url"] == "http://new-url"
        assert mock_open.call_count >= 1
        reload_call_count = mock_open.call_count
        
        # Check verify_token uses the same cache
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="new-token")
        token = verify_token(creds)
        assert token == "new-token"
        assert mock_open.call_count == reload_call_count # No new reads
        
    os.close(fd)
    os.remove(path)
