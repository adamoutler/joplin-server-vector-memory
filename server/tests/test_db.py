from db import get_db_connection
import os
import sys

# Add src to python path so we can import db
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))


def test_sqlite_vec_extension_loads():
    # Use an in-memory db for tests
    os.environ["SQLITE_DB_PATH"] = ":memory:"
    db = get_db_connection()
    cursor = db.cursor()

    # Verify sqlite-vec version
    cursor.execute("SELECT vec_version();")
    version = cursor.fetchone()[0]
    assert version is not None
    assert isinstance(version, str)

    # Insert some dummy vectors to test cosine distance
    import json
    vec1 = [0.0] * 384
    vec1[0] = 1.0
    vec2 = [0.0] * 384
    vec2[1] = 1.0

    cursor.execute("INSERT INTO note_metadata (note_id, title, content) VALUES (?, ?, ?)",
                   ("test1", "Title 1", "Content 1"))
    rowid1 = cursor.lastrowid
    cursor.execute("INSERT INTO vec_notes (rowid, embedding) VALUES (?, ?)",
                   (rowid1, json.dumps(vec1)))

    cursor.execute("INSERT INTO note_metadata (note_id, title, content) VALUES (?, ?, ?)",
                   ("test2", "Title 2", "Content 2"))
    rowid2 = cursor.lastrowid
    cursor.execute("INSERT INTO vec_notes (rowid, embedding) VALUES (?, ?)",
                   (rowid2, json.dumps(vec2)))

    db.commit()

    # Query cosine distance
    cursor.execute(f"""
        SELECT m.note_id, vec_distance_cosine(v.embedding, ?) as distance
        FROM vec_notes v
        JOIN note_metadata m ON m.rowid = v.rowid
        ORDER BY distance
    """, (json.dumps(vec1),))
    results = cursor.fetchall()

    assert len(results) == 2
    # The first result should be test1 with distance 0 (identical)
    assert results[0][0] == "test1"
    # test2 is orthogonal so cosine distance should be 1.0
    assert results[1][0] == "test2"

    db.close()
