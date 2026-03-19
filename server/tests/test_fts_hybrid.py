from src.main import search_notes, remember
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


def test_hybrid_search_fts(temp_db, mock_ollama):
    # Insert notes. All have same vector embedding from mock,
    # so distance will be same. We rely on FTS score via RRF.
    remember("Common Note 1", "This is just a regular note.")
    remember("Common Note 2", "Another note without the rare keyword.")
    remember("Specific Note", "This contains the rare keyword Xylophagalicious.")

    # Search for exact keyword
    results = search_notes("Xylophagalicious")

    # Verify the note containing the exact keyword is top
    assert len(results) > 0
    assert "Xylophagalicious" in results[0]["blurb"]
    assert results[0]["title"] == "[Agent Memory] Specific Note"
