from fastmcp import FastMCP
import ollama
import json
import uuid
import logging
import os
from src.db import get_db_connection
from sqlite_vec import serialize_float32

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("JoplinSemanticSearch")

def get_config() -> dict:
    config = {}
    config_path = os.environ.get("CONFIG_PATH", "/app/data/config.json")
    try:
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                config = json.load(f)
    except Exception as e:
        logger.error(f"Error reading config.json: {e}")
    
    return {
        "ollama_url": config.get("ollamaUrl", config.get("OLLAMA_URL", os.environ.get("OLLAMA_URL", "http://localhost:11434"))),
        "embedding_model": config.get("embeddingModel", config.get("EMBEDDING_MODEL", os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")))
    }

def get_embedding(text: str) -> list[float]:
    config = get_config()
    client = ollama.Client(host=config["ollama_url"])
    response = client.embeddings(model=config["embedding_model"], prompt=text)
    return response["embedding"]

@mcp.tool()
def search_notes(query: str) -> list[dict]:
    """
    Search notes semantically using the provided query.
    Returns the top 5 notes with their ID, Title, and a Blurb.
    """
    try:
        # nomic-embed-text requires the search_query: prefix
        embedding = get_embedding(f"search_query: {query}")
        db = get_db_connection()
        cursor = db.cursor()
        
        cursor.execute("""
            SELECT m.note_id, m.title, m.content, vec_distance_cosine(v.embedding, ?) as distance
            FROM vec_notes v
            JOIN note_metadata m ON m.rowid = v.rowid
            ORDER BY distance
            LIMIT 5
        """, (serialize_float32(embedding),))
        
        results = cursor.fetchall()
        db.close()
        
        notes = []
        for row in results:
            note_id, title, content, distance = row
            # Create a simple blurb
            blurb = content[:100] + "..." if len(content) > 100 else content
            notes.append({
                "id": note_id,
                "title": title,
                "blurb": blurb,
                "distance": distance
            })
        return notes
    except Exception as e:
        logger.error(f"Error in search_notes: {e}")
        return []

@mcp.tool()
def get_note(note_id: str) -> dict:
    """
    Get the full content of a specific note by ID.
    """
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT note_id, title, content FROM note_metadata WHERE note_id = ?", (note_id,))
    row = cursor.fetchone()
    db.close()
    
    if row:
        return {
            "id": row[0],
            "title": row[1],
            "content": row[2]
        }
    return {"error": "Note not found"}

@mcp.tool()
def remember(title: str, content: str) -> dict:
    """
    Remember a new note by storing its title and content.
    Mocks relaying to Joplin Server by directly inserting into local SQLite.
    """
    if not title.startswith("[Agent Memory] "):
        title = f"[Agent Memory] {title}"

    note_id = str(uuid.uuid4())
    try:
        embedding = get_embedding(f"{title}\n{content}")
        
        db = get_db_connection()
        cursor = db.cursor()
        
        # Insert metadata
        cursor.execute(
            "INSERT INTO note_metadata (note_id, title, content) VALUES (?, ?, ?)",
            (note_id, title, content)
        )
        rowid = cursor.lastrowid
        
        # Insert embedding
        cursor.execute(
            "INSERT INTO vec_notes (rowid, embedding) VALUES (?, ?)",
            (rowid, serialize_float32(embedding))
        )
        
        db.commit()
        db.close()
        
        return {
            "status": "success",
            "id": note_id,
            "title": title,
            "message": "Note remembered successfully (mocked relay to Joplin)."
        }
    except Exception as e:
        logger.error(f"Error in remember: {e}")
        return {"error": str(e)}

@mcp.tool()
def delete_note(note_id: str) -> dict:
    """
    Delete a note by ID.
    Mocks relaying deletion to Joplin Server.
    """
    db = get_db_connection()
    cursor = db.cursor()
    
    cursor.execute("SELECT rowid FROM note_metadata WHERE note_id = ?", (note_id,))
    row = cursor.fetchone()
    if not row:
        db.close()
        return {"error": "Note not found"}
        
    rowid = row[0]
    
    # Delete from both tables
    cursor.execute("DELETE FROM vec_notes WHERE rowid = ?", (rowid,))
    cursor.execute("DELETE FROM note_metadata WHERE note_id = ?", (note_id,))
    
    db.commit()
    db.close()
    
    return {
        "status": "success",
        "id": note_id,
        "message": "Note deleted successfully (mocked relay to Joplin)."
    }

from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import JSONResponse

# Create the Starlette/ASGI app for uvicorn
fastmcp_app = mcp.http_app(transport='sse')

def check_auth(request: Request) -> bool:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
    token = auth_header.split(" ")[1]
    
    config_path = os.environ.get("CONFIG_PATH", "/app/data/config.json")
    valid_token = None
    try:
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                config = json.load(f)
                valid_token = config.get("token")
    except Exception as e:
        logger.error(f"Error reading config for auth: {e}")
        
    if not valid_token:
        return False
        
    return token == valid_token

async def api_search(request: Request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    query = data.get("query")
    if not query:
        return JSONResponse({"error": "Missing query parameter"}, status_code=400)
    results = search_notes(query)
    return JSONResponse(results)

async def api_get(request: Request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    note_id = data.get("note_id")
    if not note_id:
        return JSONResponse({"error": "Missing note_id parameter"}, status_code=400)
    result = get_note(note_id)
    return JSONResponse(result)

async def api_remember(request: Request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    title = data.get("title")
    content = data.get("content")
    if not title or not content:
        return JSONResponse({"error": "Missing title or content parameter"}, status_code=400)
    result = remember(title, content)
    return JSONResponse(result)

async def api_delete(request: Request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    note_id = data.get("note_id")
    if not note_id:
        return JSONResponse({"error": "Missing note_id parameter"}, status_code=400)
    result = delete_note(note_id)
    return JSONResponse(result)

app = Starlette(routes=[
    Route("/api/search", api_search, methods=["POST"]),
    Route("/api/get", api_get, methods=["POST"]),
    Route("/api/remember", api_remember, methods=["POST"]),
    Route("/api/delete", api_delete, methods=["POST"]),
    Mount("/", app=fastmcp_app)
])

if __name__ == "__main__":
    import sys
    if "--stdio" in sys.argv:
        mcp.run()
    else:
        import uvicorn
        # Allow running the server locally
        uvicorn.run("main:app", host="0.0.0.0", port=8000)