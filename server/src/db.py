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
            content TEXT
        )
    """)
    
    # Create vec_notes table for sqlite-vec
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING vec0(
            embedding float[768]
        )
    """)
    
    db.commit()
