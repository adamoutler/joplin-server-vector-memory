import pytest
import os
import sys
import tempfile
from unittest.mock import patch
import hashlib
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.main import remember, get_note, request_note_deletion, execute_deletion, _deletion_tokens

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp()
    os.environ["SQLITE_DB_PATH"] = path
    yield path
    os.close(fd)
    os.remove(path)

@pytest.fixture
def mock_ollama():
    with patch('src.main.get_embedding') as mock_embed:
        def side_effect(text):
            return [0.0] * 768
        mock_embed.side_effect = side_effect
        yield mock_embed

def test_extreme_friction_invalid_token(temp_db, mock_ollama):
    result = remember("Test Note", "Content")
    note_id = result["id"]
    note = get_note(note_id)
    
    req_result = request_note_deletion(note_id, "Test")
    assert req_result["status"] == "pending"
    
    attestation = {
        "content_hash": note["content_hash"],
        "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
    }
    
    exec_result = execute_deletion("invalid_token", note["title"], attestation)
    assert exec_result.get("error") == "Invalid or expired deletion token."

def test_extreme_friction_incorrect_title(temp_db, mock_ollama):
    result = remember("Test Note", "Content")
    note_id = result["id"]
    note = get_note(note_id)
    
    req_result = request_note_deletion(note_id, "Test")
    token = req_result["deletion_token"]
    
    attestation = {
        "content_hash": note["content_hash"],
        "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
    }
    
    exec_result = execute_deletion(token, "Wrong Title", attestation)
    assert exec_result.get("error") == "confirm_title does not match the requested note's title."

def test_extreme_friction_incorrect_hash(temp_db, mock_ollama):
    result = remember("Test Note", "Content")
    note_id = result["id"]
    note = get_note(note_id)
    
    req_result = request_note_deletion(note_id, "Test")
    token = req_result["deletion_token"]
    
    attestation = {
        "content_hash": "sha256:wronghash",
        "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
    }
    
    exec_result = execute_deletion(token, note["title"], attestation)
    assert "content_hash does not match" in exec_result.get("error", "")

def test_extreme_friction_incorrect_statement(temp_db, mock_ollama):
    result = remember("Test Note", "Content")
    note_id = result["id"]
    note = get_note(note_id)
    
    req_result = request_note_deletion(note_id, "Test")
    token = req_result["deletion_token"]
    
    attestation = {
        "content_hash": note["content_hash"],
        "confirmation_statement": "I want to delete this"
    }
    
    exec_result = execute_deletion(token, note["title"], attestation)
    assert "Invalid confirmation_statement" in exec_result.get("error", "")

def test_extreme_friction_successful_loop(temp_db, mock_ollama):
    result = remember("Test Note", "Content")
    note_id = result["id"]
    note = get_note(note_id)
    
    req_result = request_note_deletion(note_id, "Test")
    token = req_result["deletion_token"]
    
    attestation = {
        "content_hash": note["content_hash"],
        "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
    }
    
    exec_result = execute_deletion(token, note["title"], attestation)
    assert exec_result.get("status") == "success"
    
    assert token not in _deletion_tokens
    
    deleted_note = get_note(note_id)
    assert deleted_note.get("error") == "Note not found"

def test_extreme_friction_expired_token(temp_db, mock_ollama):
    result = remember("Test Note", "Content")
    note_id = result["id"]
    note = get_note(note_id)
    
    req_result = request_note_deletion(note_id, "Test")
    token = req_result["deletion_token"]
    
    attestation = {
        "content_hash": note["content_hash"],
        "confirmation_statement": "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
    }
    
    _deletion_tokens[token]["expires_at"] = time.time() - 10
    
    exec_result = execute_deletion(token, note["title"], attestation)
    assert exec_result.get("error") == "Deletion token expired. Request a new one."
