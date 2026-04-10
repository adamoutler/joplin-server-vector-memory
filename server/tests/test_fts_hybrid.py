from src.main import search_notes, extract_result, remember
import pytest
import os
import sys
import tempfile
from unittest.mock import patch

# Add src to python path so we can import main and db
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp()
    os.environ["SQLITE_DB_PATH"] = path
    yield path
    os.close(fd)
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture
def mock_ollama():
    with patch('src.main.get_embedding') as mock_embed:

        def side_effect(text):
            return [0.0] * 768

        mock_embed.side_effect = side_effect
        yield mock_embed


@pytest.fixture(autouse=True)
def mock_node_proxy():
    import uuid
    with patch('src.main._call_node_proxy') as mock_proxy:
        class MockResponse:
            status_code = 200

            def __init__(self):
                self.id = str(uuid.uuid4())

            def json(self):
                return {"id": self.id}

        def side_effect(*args, **kwargs):
            return MockResponse()

        mock_proxy.side_effect = side_effect
        yield mock_proxy


def test_hybrid_search_fts(temp_db, mock_ollama):
    # Insert notes. All have same vector embedding from mock,
    # so distance will be same. We rely on FTS score via RRF.
    extract_result(remember("Common Note 1", "This is just a regular note."))
    extract_result(remember("Common Note 2", "Another note without the rare keyword."))
    extract_result(remember("Specific Note", "This contains the rare keyword Xylophagalicious."))

    # Search for exact keyword
    results = extract_result(search_notes("Xylophagalicious"))

    # Verify the note containing the exact keyword is top
    assert len(results) > 0
    assert "Xylophagalicious" in results[0]["blurb"]
    assert results[0]["title"] == "Specific Note"


def test_temporal_weighting(temp_db, mock_ollama):
    import time
    from src.db import get_db_connection

    # Insert notes
    extract_result(remember("Note A", "This is a note about a temporal topic."))
    extract_result(remember("Note B", "This is a note about a temporal topic."))

    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT rowid, title FROM note_metadata")
    rows = cursor.fetchall()

    rowid_a = next(r[0] for r in rows if r[1] == "Note A")
    rowid_b = next(r[0] for r in rows if r[1] == "Note B")

    # Make Note A 3 years old, Note B today
    now = int(time.time() * 1000)
    three_years_ago = now - (3 * 365 * 24 * 60 * 60 * 1000)

    cursor.execute("UPDATE note_metadata SET updated_time = ? WHERE rowid = ?", (three_years_ago, rowid_a))
    cursor.execute("UPDATE note_metadata SET updated_time = ? WHERE rowid = ?", (now, rowid_b))
    db.commit()

    # Search with target_date="3 years ago" and date_weight=1.0
    results_boosted_past = extract_result(search_notes("temporal topic", target_date="3 years ago", date_weight=1.0))
    assert results_boosted_past[0]["title"] == "Note A"

    # Search with target_date="now" and date_weight=1.0
    results_boosted_now = extract_result(search_notes("temporal topic", target_date="now", date_weight=1.0))
    assert results_boosted_now[0]["title"] == "Note B"
