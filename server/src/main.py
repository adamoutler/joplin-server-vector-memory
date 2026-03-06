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



from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import List, Optional
from contextlib import asynccontextmanager

class SearchRequest(BaseModel):
    query: str = Field(..., description="The semantic search query.", examples=["how to cook pasta"])

class SearchResponseItem(BaseModel):
    id: str = Field(..., description="Note ID", examples=["123e4567-e89b-12d3-a456-426614174000"])
    title: str = Field(..., description="Note Title", examples=["Pasta Recipe"])
    blurb: str = Field(..., description="Note Blurb", examples=["Boil water, add pasta..."])
    distance: float = Field(..., description="Cosine Distance", examples=[0.123])

class GetRequest(BaseModel):
    note_id: str = Field(..., description="ID of the note to retrieve", examples=["123e4567-e89b-12d3-a456-426614174000"])

class GetResponse(BaseModel):
    id: Optional[str] = Field(None, description="Note ID", examples=["123e4567-e89b-12d3-a456-426614174000"])
    title: Optional[str] = Field(None, description="Note Title", examples=["Pasta Recipe"])
    content: Optional[str] = Field(None, description="Note Content", examples=["# Pasta Recipe\n\nBoil water..."])
    error: Optional[str] = Field(None, description="Error message if any")

class RememberRequest(BaseModel):
    title: str = Field(..., description="Title of the new note", examples=["New Recipe"])
    content: str = Field(..., description="Content of the new note", examples=["# New Recipe\n\nIngredients..."])

class RememberResponse(BaseModel):
    status: Optional[str] = Field(None, description="Status of the operation", examples=["success"])
    id: Optional[str] = Field(None, description="New Note ID", examples=["123e4567-e89b-12d3-a456-426614174000"])
    title: Optional[str] = Field(None, description="New Note Title", examples=["New Recipe"])
    message: Optional[str] = Field(None, description="Success or error message", examples=["Note remembered successfully (mocked relay to Joplin)."])
    error: Optional[str] = Field(None, description="Error message if any")

class DeleteRequest(BaseModel):
    note_id: str = Field(..., description="ID of the note to delete", examples=["123e4567-e89b-12d3-a456-426614174000"])

class DeleteResponse(BaseModel):
    status: Optional[str] = Field(None, description="Status of the operation", examples=["success"])
    id: Optional[str] = Field(None, description="Deleted Note ID", examples=["123e4567-e89b-12d3-a456-426614174000"])
    message: Optional[str] = Field(None, description="Success or error message", examples=["Note deleted successfully (mocked relay to Joplin)."])
    error: Optional[str] = Field(None, description="Error message if any")

security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    config_path = os.environ.get("CONFIG_PATH", "/app/data/config.json")
    valid_token = None
    try:
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                config = json.load(f)
                valid_token = config.get("token")
    except Exception as e:
        logger.error(f"Error reading config for auth: {e}")
        
    if not valid_token or token != valid_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token

# Create the Starlette/ASGI app for uvicorn
fastmcp_app = mcp.http_app(transport='sse')
stateless_app = mcp.http_app(transport='http', stateless_http=True, path="/stateless", json_response=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with fastmcp_app.router.lifespan_context(app):
        async with stateless_app.router.lifespan_context(app):
            yield

app = FastAPI(
    title="Joplin Server Vector Memory API",
    description="API for semantic search and memory management with Joplin",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    redoc_url=None,
    lifespan=lifespan
)

@app.get("/", summary="Root Endpoint", description="Root endpoint indicating the server is running.")
async def root():
    return {"message": "Joplin Server Vector Memory API is running. Access MCP at / or /mcp-server/stateless."}

@app.post(
    "/api/search",
    response_model=List[SearchResponseItem],
    summary="Search Notes",
    description="Search notes semantically using the provided query.\n\n**Workflow Examples**:\n* **Search -> Get**: Use the `id` from a search result to fetch the full note content via `/api/get`.\n* **Search -> Delete**: Use the `id` from a search result to delete the note via `/api/delete`.",
    responses={
        200: {
            "description": "Successful Response",
            "links": {
                "GetNoteById": {
                    "operationId": "api_get_api_get_post",
                    "requestBody": {
                        "note_id": "$response.body#/0/id"
                    },
                    "description": "The `id` value returned in the response can be used as the `note_id` parameter in `POST /api/get`."
                },
                "DeleteNoteById": {
                    "operationId": "api_delete_api_delete_post",
                    "requestBody": {
                        "note_id": "$response.body#/0/id"
                    },
                    "description": "The `id` value returned in the response can be used as the `note_id` parameter in `POST /api/delete`."
                }
            }
        }
    }
)
async def api_search(request: SearchRequest, token: str = Depends(verify_token)):
    results = search_notes(request.query)
    return results

@app.post(
    "/api/get",
    response_model=GetResponse,
    summary="Get Note",
    description="Get the full content of a specific note by ID.\n\n**Workflow Examples**:\n* **Search -> Get**: Use `/api/search` to find notes, then pass the returned `id` here to retrieve the full content.\n* **Remember -> Get**: Use `/api/remember` to create a note, then pass the returned `id` here to verify its content."
)
async def api_get(request: GetRequest, token: str = Depends(verify_token)):
    result = get_note(request.note_id)
    return result

@app.post(
    "/api/remember",
    response_model=RememberResponse,
    summary="Remember Note",
    description="Remember a new note by storing its title and content.\n\n**Workflow Examples**:\n* **Remember -> Get**: Use the `id` from the response to fetch the newly created note via `/api/get`.\n* **Remember -> Delete**: Use the `id` from the response to delete the newly created note via `/api/delete`.",
    responses={
        200: {
            "description": "Successful Response",
            "links": {
                "GetNoteById": {
                    "operationId": "api_get_api_get_post",
                    "requestBody": {
                        "note_id": "$response.body#/id"
                    },
                    "description": "The `id` value returned in the response can be used as the `note_id` parameter in `POST /api/get`."
                },
                "DeleteNoteById": {
                    "operationId": "api_delete_api_delete_post",
                    "requestBody": {
                        "note_id": "$response.body#/id"
                    },
                    "description": "The `id` value returned in the response can be used as the `note_id` parameter in `POST /api/delete`."
                }
            }
        }
    }
)
async def api_remember(request: RememberRequest, token: str = Depends(verify_token)):
    result = remember(request.title, request.content)
    return result

@app.post(
    "/api/delete",
    response_model=DeleteResponse,
    summary="Delete Note",
    description="Delete a note by ID.\n\n**Workflow Examples**:\n* **Search -> Delete**: Use `/api/search` to find notes, then pass the returned `id` here to delete them.\n* **Remember -> Delete**: Use `/api/remember` to create a note, then pass the returned `id` here to clean it up."
)
async def api_delete(request: DeleteRequest, token: str = Depends(verify_token)):
    result = delete_note(request.note_id)
    return result

app.mount("/mcp-server", stateless_app)
app.mount("/", fastmcp_app)

if __name__ == "__main__":
    import sys
    if "--stdio" in sys.argv:
        mcp.run()
    else:
        import uvicorn
        # Allow running the server locally
        uvicorn.run("main:app", host="0.0.0.0", port=8000)
