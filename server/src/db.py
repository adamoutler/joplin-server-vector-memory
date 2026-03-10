import sqlite3
import sqlite_vec
import os

def get_db_connection():
    db_path = os.environ.get("SQLITE_DB_PATH", "joplin_vector.db")
    # Connect to SQLite
    db = sqlite3.connect(db_path)
    # Enable extension loading
    db.enable_load_extension(True)
    # Load sqlite-vec extension
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    
    # Initialize tables if they don't exist
    init_db(db)
    
    return db

def init_db(db):
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
    
    # Create vec_notes table for sqlite-vec
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING vec0(
            embedding float[768]
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

def reset_database():
    db_path = os.environ.get("SQLITE_DB_PATH", "joplin_vector.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    # Re-initialize
    get_db_connection()
