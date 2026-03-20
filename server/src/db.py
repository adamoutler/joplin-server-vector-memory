import sqlite3
import sqlite_vec
import os


def get_db_connection(explicit_dim=None):
    db_path = os.environ.get("SQLITE_DB_PATH", "joplin_vector.db")
    # Connect to SQLite
    db = sqlite3.connect(db_path)
    # Enable extension loading
    db.enable_load_extension(True)
    # Load sqlite-vec extension
    sqlite_vec.load(db)
    db.enable_load_extension(False)

    # Initialize tables if they don't exist
    init_db(db, explicit_dim)

    return db


def init_db(db, explicit_dim=None):
    cursor = db.cursor()

    # Create note_metadata table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS note_metadata (
            rowid INTEGER PRIMARY KEY,
            note_id TEXT UNIQUE,
            title TEXT,
            content TEXT,
            updated_time INTEGER DEFAULT 0
        )
    """)

    # Migration for updated_time
    cursor.execute("PRAGMA table_info(note_metadata)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'updated_time' not in columns:
        cursor.execute("ALTER TABLE note_metadata ADD COLUMN updated_time INTEGER DEFAULT 0")

    dim = explicit_dim
    if not dim:
        # Determine vector dimension
        config_path = os.environ.get("CONFIG_PATH", "/app/data/config.json")
        dim = 384
        if os.environ.get("OLLAMA_URL"):
            dim = 768

        try:
            import json
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = json.load(f)
                    embed_config = config.get("embedding", {})
                    if not embed_config:
                        if config.get("ollamaBaseUrl") or config.get("OLLAMA_URL"):
                            embed_config = {"provider": "ollama"}

                    if config.get("embeddingDimension"):
                        dim = int(config.get("embeddingDimension"))
                    elif embed_config.get("provider") == "ollama":
                        dim = 768
        except:
            pass

    # Create vec_notes table for sqlite-vec
    cursor.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING vec0(
            embedding float[{dim}]
        )
    """)

    # Create notes_fts table for full-text search
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
            title,
            content,
            content="note_metadata",
            content_rowid="rowid"
        )
    """)

    # Create triggers to keep notes_fts in sync
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS notes_fts_insert AFTER INSERT ON note_metadata BEGIN
            INSERT INTO notes_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content);
        END;
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS notes_fts_delete AFTER DELETE ON note_metadata BEGIN
            INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES ('delete', old.rowid, old.title, old.content);
        END;
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS notes_fts_update AFTER UPDATE ON note_metadata BEGIN
            INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES ('delete', old.rowid, old.title, old.content);
            INSERT INTO notes_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content);
        END;
    """)

    db.commit()


def reset_database(explicit_dim=None):
    db = get_db_connection(explicit_dim)
    cursor = db.cursor()
    try:
        cursor.execute("DROP TABLE IF EXISTS vec_notes")
        cursor.execute("DROP TABLE IF EXISTS notes_fts")
        cursor.execute("DROP TABLE IF EXISTS note_metadata")
        db.commit()
    except sqlite3.OperationalError:
        pass # Tables might not exist yet
    
    # Re-initialize the tables with the new dimensions
    init_db(db, explicit_dim)
    db.close()
