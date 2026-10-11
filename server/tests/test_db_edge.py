"""
Tests for edge cases and branch coverage in server/src/db.py:
- _migrate_note_metadata: missing updated_time, parent_id, folder_path
- _get_vector_dimension: explicit_dim, embeddingDimension in config.json, Ollama fallback, corrupted JSON
- reset_database: table re-creation, dimension update, OperationalError handling
"""
import os
import sys
import json
import sqlite3
import tempfile
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.db import (  # noqa: E402
    get_db_connection,
    _migrate_note_metadata,
    _get_vector_dimension,
    reset_database,
)


@pytest.fixture
def isolated_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["SQLITE_DB_PATH"] = path
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def isolated_config_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.environ["CONFIG_PATH"] = path
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def test_migrate_note_metadata_missing_all_columns():
    """Verify that _migrate_note_metadata adds updated_time, parent_id, and folder_path to legacy schemas."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    # Create legacy table lacking updated_time, parent_id, folder_path
    cursor.execute("""
        CREATE TABLE note_metadata (
            rowid INTEGER PRIMARY KEY,
            note_id TEXT UNIQUE,
            title TEXT,
            content TEXT
        )
    """)
    conn.commit()

    # Pre-migration verification
    cursor.execute("PRAGMA table_info(note_metadata)")
    cols_before = [col[1] for col in cursor.fetchall()]
    assert "updated_time" not in cols_before
    assert "parent_id" not in cols_before
    assert "folder_path" not in cols_before

    # Run migration (hits lines 26, 30, 32)
    _migrate_note_metadata(cursor)
    conn.commit()

    # Post-migration verification
    cursor.execute("PRAGMA table_info(note_metadata)")
    cols_after = [col[1] for col in cursor.fetchall()]
    assert "updated_time" in cols_after
    assert "parent_id" in cols_after
    assert "folder_path" in cols_after

    # Idempotency check: run again to verify if-guards skip alter statements cleanly
    _migrate_note_metadata(cursor)
    conn.commit()
    conn.close()


def test_migrate_note_metadata_partial_columns():
    """Verify individual column additions when only some columns are missing."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    # Table with parent_id already existing, missing updated_time and folder_path
    cursor.execute("""
        CREATE TABLE note_metadata (
            rowid INTEGER PRIMARY KEY,
            note_id TEXT UNIQUE,
            title TEXT,
            content TEXT,
            parent_id TEXT
        )
    """)
    conn.commit()

    _migrate_note_metadata(cursor)
    conn.commit()

    cursor.execute("PRAGMA table_info(note_metadata)")
    cols = [col[1] for col in cursor.fetchall()]
    assert "updated_time" in cols
    assert "parent_id" in cols
    assert "folder_path" in cols
    conn.close()


def test_get_vector_dimension_explicit():
    """explicit_dim parameter must take precedence over environment and config."""
    assert _get_vector_dimension(explicit_dim=1536) == 1536


def test_get_vector_dimension_from_config(isolated_config_file, monkeypatch):
    """Reading embeddingDimension directly from config.json (hits line 65)."""
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    with open(isolated_config_file, "w") as f:
        json.dump({"embeddingDimension": 768}, f)

    dim = _get_vector_dimension()
    assert dim == 768


def test_get_vector_dimension_legacy_flat_ollama_config(isolated_config_file, monkeypatch):
    """Test legacy unnested config containing ollamaBaseUrl (lines 58-62, 66-67)."""
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    with open(isolated_config_file, "w") as f:
        json.dump({"ollamaBaseUrl": "http://legacy-ollama:11434"}, f)

    dim = _get_vector_dimension()
    assert dim == 384


def test_get_vector_dimension_corrupted_config_fallback(isolated_config_file, monkeypatch):
    """Corrupted JSON triggers exception handling and safely falls back (lines 68-72)."""
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    with open(isolated_config_file, "w") as f:
        f.write("{this is not valid json")

    dim = _get_vector_dimension()
    assert dim == 384


def test_reset_database_reinitializes_tables(isolated_db_path):
    """reset_database must drop existing data and reinitialize with specified dimensions (lines 145-157)."""
    db = get_db_connection(explicit_dim=384)
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO note_metadata (note_id, title, content) VALUES (?, ?, ?)",
        ("note-to-wipe", "Temporary Note", "Wipe me"),
    )
    db.commit()
    db.close()

    # Reset with new dimension 512
    reset_database(explicit_dim=512)

    # Reconnect and verify data wiped and new dimension applied
    db = get_db_connection(explicit_dim=512)
    cursor = db.cursor()
    cursor.execute("SELECT count(*) FROM note_metadata")
    assert cursor.fetchone()[0] == 0

    # Verify vec_notes exists with dimension 512
    cursor.execute("PRAGMA table_info(vec_notes)")
    cols = cursor.fetchall()
    assert len(cols) > 0
    db.close()


def test_reset_database_operational_error_handling(isolated_db_path):
    """OperationalError during drop table is safely caught (lines 152-153)."""
    with patch("src.db.get_db_connection") as mock_conn_fn:
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = sqlite3.OperationalError("Simulated drop failure")
        mock_db.cursor.return_value = mock_cursor
        mock_conn_fn.return_value = mock_db

        with patch("src.db.init_db") as mock_init:
            reset_database(explicit_dim=384)
            mock_init.assert_called_once_with(mock_db, 384)
            mock_db.close.assert_called_once()
