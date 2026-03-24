from typing import Literal
import fastmcp
from contextlib import asynccontextmanager
from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import FastAPI, Depends, HTTPException, status
from fastmcp import FastMCP
import ollama
import json
import logging
import os
import hashlib
import secrets
import time
import base64
import requests
from src.db import get_db_connection
from sqlite_vec import serialize_float32
from enum import Enum
from mcp.types import ImageContent, EmbeddedResource, BlobResourceContents
from typing import Union, List, Optional
from sentence_transformers import SentenceTransformer

# Load the local model lazily to save memory if Ollama is used
_local_model = None


def get_local_model():
    global _local_model
    if _local_model is None:
        logger.info("Loading local sentence-transformers model (all-MiniLM-L6-v2)...")
        _local_model = SentenceTransformer('all-MiniLM-L6-v2')
    return _local_model


class UpdateMode(str, Enum):
    full_note_replacement = "full note replacement"
    append = "append"


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("JoplinSemanticSearch")

_config_cache = {}
_config_mtime = 0


def _load_config_file() -> dict:
    """
    Load config.json from disk, caching the result.
    The cache is invalidated if the file's modification time changes.
    """
    global _config_cache, _config_mtime
    config_path = os.environ.get("CONFIG_PATH", "/app/data/config.json")
    try:
        if os.path.exists(config_path):
            mtime = os.path.getmtime(config_path)
            # Reload if file is newer than our cached version
            if mtime > _config_mtime:
                with open(config_path, "r") as f:
                    _config_cache = json.load(f)
                _config_mtime = mtime
    except Exception as e:
        logger.error(f"Error reading config.json: {e}")
    return _config_cache


def get_config() -> dict:
    config = _load_config_file()

    # Handle legacy flat structure or new polymorphic structure
    embedding_config = config.get("embedding", {})
    if not embedding_config:
        # Backwards compatibility check
        legacy_url = config.get("ollamaBaseUrl", config.get("OLLAMA_URL", os.environ.get("OLLAMA_URL")))
        if legacy_url:
            embedding_config = {
                "provider": "ollama",
                "baseUrl": legacy_url,
                "model": config.get("embeddingModel", config.get("EMBEDDING_MODEL", os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")))
            }
        else:
            embedding_config = {"provider": "internal"}

    return {
        "embedding": embedding_config,
        "joplin_server_url": config.get("joplinServerUrl", config.get("JOPLIN_SERVER_URL", os.environ.get("JOPLIN_SERVER_URL", ""))),
        "joplin_username": config.get("joplinUsername", config.get("JOPLIN_USERNAME", os.environ.get("JOPLIN_USERNAME", ""))),
        "joplin_password": config.get("joplinPassword", config.get("JOPLIN_PASSWORD", os.environ.get("JOPLIN_PASSWORD", ""))),
    }


def get_embedding(text: Union[str, List[str]]) -> Union[list[float], list[list[float]]]:
    config = get_config()
    embed_config = config.get("embedding", {})

    is_batch = isinstance(text, list)
    texts = text if is_batch else [text]

    # If Ollama URL is provided, use external Ollama server exclusively
    if embed_config.get("provider") == "ollama" and embed_config.get("baseUrl"):
        client = ollama.Client(host=embed_config["baseUrl"])

        SAFE_BATCH_SIZE = 8
        all_embeddings = []

        def fetch_single_with_retry(t: str) -> list[float]:
            current_text = t
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = client.embed(model=embed_config["model"], input=[current_text])
                    return response["embeddings"][0]
                except Exception as e:
                    error_msg = str(e).lower()
                    if "context length" in error_msg or "size limit" in error_msg or "too long" in error_msg:
                        if attempt < max_retries - 1:
                            logger.warning(f"Ollama context length exceeded. Truncating text and retrying (attempt {attempt + 1})...")
                            current_text = current_text[:len(current_text) // 2]
                            continue
                    logger.error(f"Ollama embedding failed critically on single item: {e}")
                    raise RuntimeError(str(e))

        def fetch_chunk(chunk: List[str]) -> List[list[float]]:
            try:
                response = client.embed(model=embed_config["model"], input=chunk)
                return response["embeddings"]
            except Exception as e:
                error_msg = str(e).lower()
                if "context length" in error_msg or "size limit" in error_msg or "too long" in error_msg:
                    logger.warning(f"Batch of {len(chunk)} hit a context length limit. Falling back to sequential processing.")
                    chunk_embeddings = []
                    for t in chunk:
                        chunk_embeddings.append(fetch_single_with_retry(t))
                    return chunk_embeddings
                else:
                    logger.error(f"Ollama batch embedding failed critically: {e}")
                    raise RuntimeError(str(e))

        chunks = [texts[i:i + SAFE_BATCH_SIZE] for i in range(0, len(texts), SAFE_BATCH_SIZE)]

        import concurrent.futures
        # Use 3 concurrent workers to send 3 arrays of 8 simultaneously (24 total embeddings in flight)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(fetch_chunk, chunks))

        for res in results:
            all_embeddings.extend(res)

        return all_embeddings if is_batch else all_embeddings[0]

    # Fallback to completely local CPU embedding
    model = get_local_model()
    embeddings = model.encode(texts).tolist()
    return embeddings if is_batch else embeddings[0]


def _call_node_proxy(method: str, path: str, json_data: dict = None) -> requests.Response:
    config = get_config()
    username = config.get("joplin_username", "")
    password = config.get("joplin_password", "")
    base_url = os.environ.get("NODE_PROXY_URL", "http://127.0.0.1:3000")
    url = f"{base_url}{path}"
    # Node proxy expects Basic Auth on some routes, but /node-api is internally bypassed.
    # However, keeping auth here is fine just in case.
    auth = (username, password) if username and password else None

    if method.upper() == "GET":
        return requests.get(url, auth=auth)
    elif method.upper() == "POST":
        return requests.post(url, json=json_data, auth=auth)
    return requests.request(method, url, auth=auth)


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

        # 1. Vector Search using CTE MATCH pattern
        cursor.execute("""
            WITH knn_matches AS (
                SELECT rowid, distance
                FROM vec_notes
                WHERE embedding MATCH ? AND k = 5
            )
            SELECT m.rowid, m.note_id, m.title, m.content, k.distance
            FROM knn_matches k
            JOIN note_metadata m ON m.rowid = k.rowid
            ORDER BY k.distance
        """, (serialize_float32(embedding),))
        vec_results = cursor.fetchall()

        # 2. FTS Search for exact keywords
        # Sanitize query for FTS phrase search to prevent syntax errors
        sanitized_query = query.replace('"', '""')
        fts_query = f'"{sanitized_query}"'

        try:
            cursor.execute("""
                SELECT m.rowid, m.note_id, m.title, m.content, bm25(notes_fts) as score
                FROM notes_fts f
                JOIN note_metadata m ON m.rowid = f.rowid
                WHERE notes_fts MATCH ?
                ORDER BY score
                LIMIT 5
            """, (fts_query,))
            fts_results = cursor.fetchall()
        except Exception as e:
            logger.warning(
                f"FTS search failed (likely syntax error in query), proceeding with only vector results: {e}")
            fts_results = []

        db.close()

        # 3. Reciprocal Rank Fusion (RRF)
        rrf_scores = {}
        notes_data = {}

        for rank, row in enumerate(vec_results):
            rowid, note_id, title, content, distance = row
            if rowid not in rrf_scores:
                rrf_scores[rowid] = 0
                notes_data[rowid] = {"id": note_id, "title": title, "content": content}
            rrf_scores[rowid] += 1.0 / (rank + 60)

        for rank, row in enumerate(fts_results):
            rowid, note_id, title, content, score = row
            if rowid not in rrf_scores:
                rrf_scores[rowid] = 0
                notes_data[rowid] = {"id": note_id, "title": title, "content": content}
            rrf_scores[rowid] += 1.0 / (rank + 60)

        # Sort by RRF score descending
        sorted_rowids = sorted(rrf_scores.keys(), key=lambda r: rrf_scores[r], reverse=True)
        top_rowids = sorted_rowids[:5]

        notes = []
        for i, rowid in enumerate(top_rowids):
            data = notes_data[rowid]
            note_id = data["id"]
            if isinstance(note_id, bytes):
                note_id = note_id.hex()
            elif isinstance(note_id, str):
                note_id = note_id.replace("-", "")

            # Create a simple blurb
            content = data["content"]
            blurb = content[:2000] + "..." if len(content) > 2000 else content

            note_dict = {
                "id": note_id,
                "title": data["title"],
                "blurb": blurb,
                "distance": rrf_scores[rowid]  # We return RRF score here as 'distance'
            }
            if i == 0:
                note_dict["full_body"] = content

            notes.append(note_dict)
        return notes
    except Exception as e:
        logger.error(f"Error in search_notes: {e}")
        return []


@mcp.tool()
def get_resource(resource_id: str) -> Union[str, ImageContent, EmbeddedResource]:
    """
    Get the contents of a specific resource (image, script, PDF, etc) attached to a note.
    """
    try:
        res = _call_node_proxy("GET", f"/node-api/resources/{resource_id}")
        if res.status_code != 200:
            return f"Error fetching resource: {res.text}"

        content_type = res.headers.get("Content-Type", "application/octet-stream")

        if content_type.startswith("text/") or content_type in ["application/json", "application/x-sh", "application/javascript"]:
            return res.text

        b64_data = base64.b64encode(res.content).decode("utf-8")

        if content_type.startswith("image/"):
            return ImageContent(type="image", mimeType=content_type, data=b64_data)

        return EmbeddedResource(
            type="resource",
            resource=BlobResourceContents(
                uri=f"joplin://resource/{resource_id}",
                mimeType=content_type,
                blob=b64_data
            )
        )
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def upload_resource(filename: str, base64_data: str, mime_type: str = None) -> str:
    """
    Uploads a binary file or resource to the server.
    Returns a unique Resource ID that can be referenced while updating or remembering a note.
    To attach the file to a note, embed the returned ID into the markdown content using the syntax `[filename](:/RESOURCE_ID)` or `![filename](:/RESOURCE_ID)`.
    """
    try:
        payload = {
            "filename": filename,
            "base64_data": base64_data
        }
        if mime_type:
            payload["mime_type"] = mime_type

        res = _call_node_proxy("POST", "/node-api/resources", json_data=payload)
        if res.status_code == 200:
            return json.dumps(res.json())
        return f"Error uploading resource: {res.text}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def get_note(note_id: str) -> dict:
    """
    Get the full content of a specific note by ID.
    """
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT note_id, title, content, updated_time FROM note_metadata WHERE note_id = ?", (note_id,))
    row = cursor.fetchone()
    db.close()

    if row:
        content = row[2]
        content_hash = "sha256:" + hashlib.sha256(content.encode('utf-8')).hexdigest()

        resources = []
        try:
            res = _call_node_proxy("GET", f"/node-api/notes/{note_id}/resources")
            if res.status_code == 200:
                resources = res.json()
        except Exception as e:
            logger.warning(f"Failed to fetch resources for note {note_id}: {e}")

        return {
            "id": row[0],
            "title": row[1],
            "content": content,
            "updated_time": row[3],
            "content_hash": content_hash,
            "resources": resources
        }
    return {"error": "Note not found"}


@mcp.tool()
def remember(title: str, content: str, folder: str = "Agent Memory") -> dict:
    """
    Remember a new note by storing its title and content.
    Relays to Joplin Server via the Node.js proxy, then updates local SQLite for instant searchability.

    folder: Optional, discouraged, folder to save the note in. Defaults to "Agent Memory".

    ATTACHING FILES: If you need to attach a file, script, or image to this note,
    you must FIRST call the `upload_resource` tool. That tool will return an ID.
    You must then embed that ID into the `content` of this note using standard
    Joplin markdown syntax: `[link text](:/THE_RETURNED_ID)` or `![image](:/THE_RETURNED_ID)`.
    """
    try:
        # 1. Relay to Joplin via Node Proxy
        res = _call_node_proxy("POST", "/node-api/notes", json_data={"title": title, "body": content, "folder": folder})
        if res.status_code != 200:
            return {"error": f"Failed to create note in Joplin: {res.text}"}

        note_id = res.json().get("id")
        if not note_id:
            return {"error": "Failed to get note ID from Joplin."}

        # 2. Update local SQLite for instant searchability
        embedding = get_embedding(f"{title}\n{content}")

        db = get_db_connection()
        cursor = db.cursor()

        updated_time = int(time.time() * 1000)  # Joplin uses ms typically, but we should match what sync.js uses
        cursor.execute(
            "INSERT INTO note_metadata (note_id, title, content, updated_time) VALUES (?, ?, ?, ?)",
            (note_id, title, content, updated_time)
        )
        rowid = cursor.lastrowid

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
            "message": "Note remembered successfully and synced to Joplin."
        }
    except Exception as e:
        logger.error(f"Error in remember: {e}")
        return {"error": str(e)}


@mcp.tool()
def update_note(note_id: str, content: str, update_mode: UpdateMode, last_modified_timestamp: int, summary_of_changes: str) -> dict:
    """
    Update an existing note. Implement Optimistic Concurrency Control using last_modified_timestamp.
    update_mode can be 'full note replacement' or 'append'.
    summary_of_changes is a description of the changes made for record keeping (not currently stored).
    """
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT title, content, updated_time, rowid FROM note_metadata WHERE note_id = ?", (note_id,))
    row = cursor.fetchone()

    if not row:
        db.close()
        return {"error": "Note not found"}

    title, current_content, current_time, rowid = row

    if last_modified_timestamp != current_time:
        db.close()
        return {"error": "Error: Note has been modified since you last read it. Retrieve the note again before updating."}

    if update_mode == UpdateMode.append:
        new_content = current_content + "\n" + content
    elif update_mode == UpdateMode.full_note_replacement:
        new_content = content
    else:
        db.close()
        return {"error": "Invalid update_mode. Must be 'append' or 'full note replacement'."}

    new_time = int(time.time() * 1000)

    try:
        embedding = get_embedding(f"{title}\n{new_content}")

        cursor.execute(
            "UPDATE note_metadata SET content = ?, updated_time = ? WHERE note_id = ?",
            (new_content, new_time, note_id)
        )

        cursor.execute(
            "UPDATE vec_notes SET embedding = ? WHERE rowid = ?",
            (serialize_float32(embedding), rowid)
        )

        db.commit()
        db.close()

        return {
            "status": "success",
            "id": note_id
        }
    except Exception as e:
        logger.error(f"Error in update_note: {e}")
        db.rollback()
        db.close()
        return {"error": str(e)}


_deletion_tokens = {}


@mcp.tool()
def request_note_deletion(note_id: str, reason: str) -> dict:
    """
    Request the deletion of a note. This is step 1 of 2.
    Returns a token required for step 2.
    """
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT title FROM note_metadata WHERE note_id = ?", (note_id,))
    row = cursor.fetchone()
    db.close()

    if not row:
        return {"error": "Note not found"}

    title = row[0]
    token = secrets.token_hex(8)
    expires_at = time.time() + 300  # 5 minutes

    _deletion_tokens[token] = {
        "note_id": note_id,
        "title": title,
        "expires_at": expires_at
    }

    return {
        "status": "pending",
        "message": "Deletion requested. To complete deletion, call execute_deletion with this token, the exact note title, and the required safety attestation.",
        "deletion_token": token,
        "note_id": note_id,
        "confirm_title": title,
        "expires_in_seconds": 300
    }


@mcp.tool()
def execute_deletion(deletion_token: str, confirm_title: str, safety_attestation: dict) -> dict:
    """
    Execute the deletion of a note. This is step 2 of 2.
    Requires the token from step 1, the exact note title, and a safety attestation.
    """
    if deletion_token not in _deletion_tokens:
        return {"error": "Invalid or expired deletion token."}

    token_data = _deletion_tokens[deletion_token]

    if time.time() > token_data["expires_at"]:
        del _deletion_tokens[deletion_token]
        return {"error": "Deletion token expired. Request a new one."}

    if confirm_title != token_data["title"]:
        return {"error": "confirm_title does not match the requested note's title."}

    if not isinstance(safety_attestation, dict) or "content_hash" not in safety_attestation or "confirmation_statement" not in safety_attestation:
        return {"error": "safety_attestation must contain 'content_hash' and 'confirmation_statement'."}

    expected_statement = "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered."
    if safety_attestation["confirmation_statement"] != expected_statement:
        return {"error": f"Invalid confirmation_statement. Must be exactly: '{expected_statement}'"}

    note_id = token_data["note_id"]

    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT content FROM note_metadata WHERE note_id = ?", (note_id,))
    row = cursor.fetchone()

    if not row:
        db.close()
        del _deletion_tokens[deletion_token]
        return {"error": "Note not found during execution."}

    content = row[0]
    expected_hash = "sha256:" + hashlib.sha256(content.encode('utf-8')).hexdigest()

    if safety_attestation["content_hash"] != expected_hash:
        db.close()
        return {"error": f"content_hash does not match the note's content. Expected {expected_hash}"}

    try:
        # 1. Relay to Joplin via Node Proxy
        res = _call_node_proxy("DELETE", f"/node-api/notes/{note_id}")
        if res.status_code != 200:
            db.close()
            return {"error": f"Failed to delete note in Joplin: {res.text}"}

        # 2. Update local SQLite
        cursor.execute("SELECT rowid FROM note_metadata WHERE note_id = ?", (note_id,))
        rowid_row = cursor.fetchone()
        if rowid_row:
            rowid = rowid_row[0]
            # Delete from tables
            cursor.execute("DELETE FROM vec_notes WHERE rowid = ?", (rowid,))
            cursor.execute("DELETE FROM note_metadata WHERE note_id = ?", (note_id,))
        db.commit()
    except Exception as e:
        db.rollback()
        db.close()
        return {"error": f"Error deleting note: {str(e)}"}
    finally:
        db.close()

    del _deletion_tokens[deletion_token]

    return {
        "status": "success",
        "id": note_id,
        "message": "Note deleted successfully and synced to Joplin."
    }


class InternalEmbedRequest(BaseModel):
    texts: List[str]


class InternalEmbeddingSettings(BaseModel):
    provider: Literal["internal"] = "internal"


class OllamaEmbeddingSettings(BaseModel):
    provider: Literal["ollama"] = "ollama"
    baseUrl: str = ""
    model: str = ""


class Settings(BaseModel):
    embedding: Union[OllamaEmbeddingSettings, InternalEmbeddingSettings] = Field(default_factory=InternalEmbeddingSettings)
    chunkSize: int = 1000
    chunkOverlap: int = 200
    searchTopK: int = 5
    hybridAlpha: float = 0.5
    syncInterval: int = 300
    syncMaxRetries: int = 3
    joplinServerUrl: str = ""
    joplinUsername: str = ""
    joplinPassword: str = ""
    joplinMasterPassword: str = ""
    memoryServerAddress: str = ""


class SettingsUpdate(BaseModel):
    embedding: Optional[Union[OllamaEmbeddingSettings, InternalEmbeddingSettings]] = None
    chunkSize: Optional[int] = None
    chunkOverlap: Optional[int] = None
    searchTopK: Optional[int] = None
    hybridAlpha: Optional[float] = None
    syncInterval: Optional[int] = None
    syncMaxRetries: Optional[int] = None
    joplinServerUrl: Optional[str] = None
    joplinUsername: Optional[str] = None
    joplinPassword: Optional[str] = None
    joplinMasterPassword: Optional[str] = None
    memoryServerAddress: Optional[str] = None
    reindex_approved: bool = False


class SearchRequest(BaseModel):
    query: str = Field(..., description="The semantic search query.", examples=["how to cook pasta"])


class SearchResponseItem(BaseModel):
    id: str = Field(..., description="Note ID", examples=["123e4567-e89b-12d3-a456-426614174000"])
    title: str = Field(..., description="Note Title", examples=["Pasta Recipe"])
    blurb: str = Field(..., description="Note Blurb", examples=["Boil water, add pasta..."])
    distance: float = Field(..., description="Cosine Distance", examples=[0.123])
    full_body: Optional[str] = Field(None, description="Full content of the note (only included for the top result)", examples=[
                                     "# Pasta Recipe\n\nBoil water..."])


class GetRequest(BaseModel):
    note_id: str = Field(..., description="ID of the note to retrieve",
                         examples=["123e4567-e89b-12d3-a456-426614174000"])


class GetResponse(BaseModel):
    id: Optional[str] = Field(None, description="Note ID", examples=["123e4567-e89b-12d3-a456-426614174000"])
    title: Optional[str] = Field(None, description="Note Title", examples=["Pasta Recipe"])
    content: Optional[str] = Field(None, description="Note Content", examples=["# Pasta Recipe\n\nBoil water..."])
    updated_time: Optional[int] = Field(None, description="Last updated timestamp", examples=[1628000000])
    content_hash: Optional[str] = Field(None, description="SHA256 hash of the content")
    error: Optional[str] = Field(None, description="Error message if any")


class RememberRequest(BaseModel):
    title: str = Field(..., description="Title of the new note", examples=["New Recipe"])
    content: str = Field(..., description="Content of the new note", examples=["# New Recipe\n\nIngredients..."])
    folder: str = Field("Agent Memory", description="Optional folder name to save the note in",
                        examples=["Agent Memory"])


class RememberResponse(BaseModel):
    status: Optional[str] = Field(None, description="Status of the operation", examples=["success"])
    id: Optional[str] = Field(None, description="New Note ID", examples=["123e4567-e89b-12d3-a456-426614174000"])
    title: Optional[str] = Field(None, description="New Note Title", examples=["New Recipe"])
    message: Optional[str] = Field(None, description="Success or error message", examples=[
                                   "Note remembered successfully and synced to Joplin."])
    error: Optional[str] = Field(None, description="Error message if any")


class RequestDeletionRequest(BaseModel):
    note_id: str = Field(..., description="ID of the note to request deletion for",
                         examples=["123e4567-e89b-12d3-a456-426614174000"])
    reason: str = Field(..., description="Reason for deletion")


class RequestDeletionResponse(BaseModel):
    status: Optional[str] = Field(None, description="Status of the operation")
    message: Optional[str] = Field(None, description="Instructions to complete deletion")
    deletion_token: Optional[str] = Field(None, description="Token required to execute deletion")
    note_id: Optional[str] = Field(None, description="Note ID")
    confirm_title: Optional[str] = Field(None, description="Exact note title required for execution")
    expires_in_seconds: Optional[int] = Field(None, description="Seconds until the token expires")
    error: Optional[str] = Field(None, description="Error message if any")


class SafetyAttestation(BaseModel):
    content_hash: str = Field(..., description="SHA256 hash of the content")
    confirmation_statement: str = Field(..., description="Statement confirming destruction")


class ExecuteDeletionRequest(BaseModel):
    deletion_token: str = Field(..., description="Token from request-deletion")
    confirm_title: str = Field(..., description="Exact note title")
    safety_attestation: SafetyAttestation = Field(..., description="Safety attestation object")


class ExecuteDeletionResponse(BaseModel):
    status: Optional[str] = Field(None, description="Status of the operation", examples=["success"])
    id: Optional[str] = Field(None, description="Deleted Note ID", examples=["123e4567-e89b-12d3-a456-426614174000"])
    message: Optional[str] = Field(None, description="Success or error message", examples=[
                                   "Note deleted successfully and synced to Joplin."])
    error: Optional[str] = Field(None, description="Error message if any")


class UpdateRequest(BaseModel):
    note_id: str = Field(..., description="ID of the note to update")
    content: str = Field(..., description="New content to append or replace")
    update_mode: UpdateMode = Field(..., description="Mode of update: 'replace' or 'append'")
    last_modified_timestamp: int = Field(..., description="Timestamp for Optimistic Concurrency Control")
    summary_of_changes: str = Field(..., description="Summary of changes")


class UpdateResponse(BaseModel):
    status: Optional[str] = Field(None, description="Status of the operation")
    id: Optional[str] = Field(None, description="Updated Note ID")
    error: Optional[str] = Field(None, description="Error message if any")


security = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    import datetime
    token = credentials.credentials
    is_valid = False
    try:
        config = _load_config_file()
        api_keys = config.get("api_keys", [])

        current_time = datetime.datetime.now(datetime.timezone.utc)
        for key_obj in api_keys:
            if key_obj.get("key") == token:
                expires_at = key_obj.get("expires_at")
                if expires_at is None:
                    is_valid = True
                    break
                try:
                    expires_date = datetime.datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                    if expires_date.tzinfo is None:
                        expires_date = expires_date.replace(tzinfo=datetime.timezone.utc)
                    if expires_date > current_time:
                        is_valid = True
                        break
                except Exception as parse_err:
                    logger.error(f"Error parsing token expiration: {parse_err}")
    except Exception as e:
        logger.error(f"Error reading config for auth: {e}")

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


# Configure FastMCP global settings for absolute paths (to avoid 404s when mounted at root)
fastmcp.settings.sse_path = "/http-api/mcp/sse"
fastmcp.settings.message_path = "/http-api/mcp/sse/messages"
fastmcp.settings.streamable_http_path = "/http-api/mcp/stream"

# Create the Starlette/ASGI app for uvicorn
fastmcp_app = mcp.http_app(transport='sse')
stateless_app = mcp.http_app(transport='http', stateless_http=True, path="/http-api/mcp/stateless", json_response=True)
streamable_app = mcp.http_app(transport='streamable-http')


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with fastmcp_app.router.lifespan_context(app):
        async with stateless_app.router.lifespan_context(app):
            async with streamable_app.router.lifespan_context(app):
                yield

app = FastAPI(
    title="Joplin Server Vector Memory API",
    description="API for semantic search and memory management with Joplin",
    version="1.0.0",
    docs_url=None,
    openapi_url=None,
    redoc_url=None,
    lifespan=lifespan
)


@app.get("/", summary="Root Endpoint", description="Root endpoint indicating the server is running.")
async def root():
    return {"message": "Joplin Server Vector Memory API is running. Access MCP at / or /mcp-server/stateless."}


@app.post("/http-api/internal/embed")
def internal_embed(request: InternalEmbedRequest):
    """
    Internal endpoint for the Node.js sync daemon to request embeddings
    without needing to know if we are using Ollama or a local model.
    """
    try:
        embeddings = get_embedding(request.texts)
        return {"embeddings": embeddings}
    except Exception as e:
        logger.error(f"Error generating internal embedding: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/http-api/search",
    response_model=List[SearchResponseItem],
    summary="Search Notes",
    description="Search notes semantically using the provided query.\n\n**Workflow Examples**:\n* **Search -> Get**: Use the `id` from a search result to fetch the full note content via `/api/get`.\n* **Search -> Delete**: Use the `id` from a search result to delete the note via `/api/delete`.",
    responses={
        200: {
            "description": "Successful Response",
            "links": {
                "GetNoteById": {
                    "operationId": "api_get_http_api_get_post",
                    "requestBody": {
                        "note_id": "$response.body#/0/id"
                    },
                    "description": "The `id` value returned in the response can be used as the `note_id` parameter in `POST /http-api/get`."
                },
                "RequestDeletionById": {
                    "operationId": "api_request_deletion_http_api_request_deletion_post",
                    "requestBody": {
                        "note_id": "$response.body#/0/id",
                        "reason": "Note no longer needed"
                    },
                    "description": "The `id` value returned in the response can be used as the `note_id` parameter in `POST /http-api/request-deletion`."
                }
            }
        }
    }
)
async def api_search(request: SearchRequest, token: str = Depends(verify_token)):
    results = search_notes(request.query)
    return results


@app.post(
    "/http-api/get",
    response_model=GetResponse,
    summary="Get Note",
    description="Get the full content of a specific note by ID.\n\n**Workflow Examples**:\n* **Search -> Get**: Use `/api/search` to find notes, then pass the returned `id` here to retrieve the full content.\n* **Remember -> Get**: Use `/api/remember` to create a note, then pass the returned `id` here to verify its content."
)
async def api_get(request: GetRequest, token: str = Depends(verify_token)):
    result = get_note(request.note_id)
    return result


@app.post(
    "/http-api/remember",
    response_model=RememberResponse,
    summary="Remember Note",
    description="Remember a new note by storing its title and content.\n\n**Workflow Examples**:\n* **Remember -> Get**: Use the `id` from the response to fetch the newly created note via `/api/get`.\n* **Remember -> Delete**: Use the `id` from the response to delete the newly created note via `/api/delete`.",
    responses={
        200: {
            "description": "Successful Response",
            "links": {
                "GetNoteById": {
                    "operationId": "api_get_http_api_get_post",
                    "requestBody": {
                        "note_id": "$response.body#/id"
                    },
                    "description": "The `id` value returned in the response can be used as the `note_id` parameter in `POST /http-api/get`."
                },
                "RequestDeletionById": {
                    "operationId": "api_request_deletion_http_api_request_deletion_post",
                    "requestBody": {
                        "note_id": "$response.body#/id",
                        "reason": "Note no longer needed"
                    },
                    "description": "The `id` value returned in the response can be used as the `note_id` parameter in `POST /http-api/request-deletion`."
                }
            }
        }
    }
)
async def api_remember(request: RememberRequest, token: str = Depends(verify_token)):
    result = remember(request.title, request.content, request.folder)
    return result


@app.post(
    "/http-api/request-deletion",
    response_model=RequestDeletionResponse,
    summary="Request Note Deletion",
    description="Step 1 of the high-friction deletion process. Request the deletion of a note by ID. Returns a token."
)
async def api_request_deletion(request: RequestDeletionRequest, token: str = Depends(verify_token)):
    res = request_note_deletion(request.note_id, request.reason)
    if "error" in res:
        return RequestDeletionResponse(error=res["error"])
    return RequestDeletionResponse(**res)


@app.post(
    "/http-api/execute-deletion",
    response_model=ExecuteDeletionResponse,
    summary="Execute Note Deletion",
    description="Step 2 of the high-friction deletion process. Requires the token from step 1, exact note title, and safety attestation."
)
async def api_execute_deletion(request: ExecuteDeletionRequest, token: str = Depends(verify_token)):
    res = execute_deletion(request.deletion_token, request.confirm_title, request.safety_attestation.model_dump())
    if "error" in res:
        return ExecuteDeletionResponse(error=res["error"])
    return ExecuteDeletionResponse(**res)


@app.post("/http-api/update",
          response_model=UpdateResponse,
          summary="Update Note",
          description="Update an existing note by appending or replacing its content.\n\nRequires the note_id, new content, update_mode ('full_replace' or 'append'), last_modified_timestamp for concurrency control, and a summary_of_changes."
          )
async def api_update(request: UpdateRequest, token: str = Depends(verify_token)):
    result = update_note(
        note_id=request.note_id,
        content=request.content,
        update_mode=request.update_mode,
        last_modified_timestamp=request.last_modified_timestamp,
        summary_of_changes=request.summary_of_changes
    )
    return result


@app.get("/api/settings", response_model=Settings)
async def get_settings(token: str = Depends(verify_token)):
    config = _load_config_file()
    # Extract only valid fields for Settings
    valid_keys = Settings.schema()["properties"].keys() if hasattr(Settings, "schema") else Settings.model_fields.keys()
    settings_dict = {k: v for k, v in config.items() if k in valid_keys}
    return Settings(**settings_dict)


class TestModelRequest(BaseModel):
    baseUrl: str
    model: str


@app.post("/api/settings/test-model")
async def test_model_connection(request: TestModelRequest, token: str = Depends(verify_token)):
    if not request.baseUrl:
        return {"success": True, "dimension": 384}  # Local model
    try:
        import ollama
        client = ollama.Client(host=request.baseUrl)
        try:
            client.show(request.model)
        except Exception:
            client.pull(request.model)
        res = client.embeddings(model=request.model, prompt="test")
        if "embedding" in res:
            return {"success": True, "dimension": len(res["embedding"])}
        else:
            raise ValueError("Response did not contain an embedding array.")
    except Exception as e:
        logger.error(f"Model test failed: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to connect to or pull model '{request.model}' from '{request.baseUrl}': {str(e)}")


@app.post("/api/settings", response_model=Settings)
async def update_settings(settings_update: SettingsUpdate, token: str = Depends(verify_token)):
    global _config_mtime
    _config_mtime = 0  # Force reload to prevent caching race conditions
    current_config = _load_config_file()

    # Handle both Pydantic v1 and v2
    if hasattr(settings_update, "model_dump"):
        new_config = settings_update.model_dump(exclude={"reindex_approved"}, exclude_none=True)
    else:
        new_config = settings_update.dict(exclude={"reindex_approved"}, exclude_none=True)

    # Check for critical changes
    critical_keys = ["chunkSize", "chunkOverlap"]
    critical_changed = any(current_config.get(k) != new_config.get(k) for k in critical_keys if k in new_config)

    # Check if embedding changed
    current_embed = current_config.get("embedding", {})
    new_embed = new_config.get("embedding", {})
    if new_embed and current_embed != new_embed:
        critical_changed = True

    if critical_changed and settings_update.reindex_approved:
        # Determine actual dimensionality before wiping
        new_dim = 384
        if new_embed.get("provider") == "ollama" and new_embed.get("baseUrl"):
            try:
                import ollama
                client = ollama.Client(host=new_embed["baseUrl"])
                # Pull the model if it doesn't exist
                try:
                    client.show(new_embed["model"])
                except:
                    client.pull(new_embed["model"])
                # Generate a tiny embedding to measure its length
                res = client.embeddings(model=new_embed["model"], prompt="test")
                if "embedding" in res:
                    new_dim = len(res["embedding"])
            except Exception as e:
                logger.error(f"Failed to determine dimensions for model {new_embed.get('model')}: {e}")
                raise HTTPException(status_code=400, detail=f"Failed to connect to model {new_embed.get('model')} at {new_embed.get('baseUrl')}: {str(e)}")

        new_config["embeddingDimension"] = new_dim

        # Maintenance Shutdown Procedure:
        # This lock-and-confirm handshake prevents catastrophic race conditions where Python resets the DB
        # and overwrites config.json while Node is simultaneously shutting down or restarting.
        # Without this, config.json gets corrupted, permanently locking users out of the UI.
        # Do not remove this logic.
        lock_file = "/tmp/maintenance.lock"
        confirm_file = "/tmp/maintenance.confirm"

        # 1. Create lock
        with open(lock_file, "w") as f:
            f.write("lock")

        # 2. Tell the Node.js daemon to restart so it drops ghost file handles and re-syncs
        try:
            import requests
            requests.post("http://127.0.0.1:3000/node-api/restart", timeout=2)
        except Exception as e:
            logger.error(f"Failed to restart Node daemon: {e}")

        # 5. Wait for confirm
        import time
        max_wait = 15
        start_wait = time.time()
        while not os.path.exists(confirm_file) and time.time() - start_wait < max_wait:
            time.sleep(0.5)

        # 6. Safely drop DB
        from src.db import reset_database
        reset_database(new_dim)

    merged_config = {**current_config, **new_config}

    # Save to config.json atomically
    config_path = os.environ.get("CONFIG_PATH", "/app/data/config.json")
    # Make sure directory exists
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    tmp_config_path = f"{config_path}.tmp"
    with open(tmp_config_path, "w") as f:
        json.dump(merged_config, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_config_path, config_path)

    # 7. Delete the lock file
    if critical_changed and settings_update.reindex_approved:
        if os.path.exists("/tmp/maintenance.lock"):
            os.remove("/tmp/maintenance.lock")
        if os.path.exists("/tmp/maintenance.confirm"):
            os.remove("/tmp/maintenance.confirm")

    _config_mtime = 0  # Invalidate cache

    return Settings(**new_config)


@app.post("/api/settings/reset", response_model=Settings)
async def reset_settings(token: str = Depends(verify_token)):
    default_settings = Settings()
    current_config = _load_config_file()

    if hasattr(default_settings, "model_dump"):
        default_dict = default_settings.model_dump()
    else:
        default_dict = default_settings.dict()

    merged_config = {**current_config, **default_dict}

    config_path = os.environ.get("CONFIG_PATH", "/app/data/config.json")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    tmp_config_path = f"{config_path}.tmp"
    with open(tmp_config_path, "w") as f:
        json.dump(merged_config, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_config_path, config_path)

    global _config_mtime
    _config_mtime = 0  # Invalidate cache

    return default_settings

# Actually, let's just append the routes directly
for route in fastmcp_app.routes:
    app.routes.append(route)
for route in streamable_app.routes:
    app.routes.append(route)
for route in stateless_app.routes:
    app.routes.append(route)


class ForceAcceptJSONMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            original_path = scope["path"]
            method = scope.get("method", "")

            # Map exact /http-api/mcp based on method for Gemini CLI compatibility
            if original_path.startswith("/http-api/mcp"):
                # If it's explicitly one of the mounted sub-apps, leave it alone
                if not any(original_path.startswith(p) for p in ["/http-api/mcp/sse", "/http-api/mcp/stream", "/http-api/mcp/stateless"]):
                    # It's a bare /http-api/mcp or a subpath like /http-api/mcp/messages
                    subpath = original_path[len("/http-api/mcp"):]
                    if not subpath or subpath == "/":
                        if method == "GET":
                            scope["path"] = "/http-api/mcp/sse"
                        else:
                            scope["path"] = "/http-api/mcp/stateless"
                    else:
                        if method == "GET":
                            scope["path"] = f"/http-api/mcp/sse{subpath}"
                        else:
                            scope["path"] = f"/http-api/mcp/sse{subpath}"

            logger.info(f"[MIDDLEWARE] {method} {original_path} -> {scope['path']}")

            if scope["path"].startswith("/http-api/mcp") and "sse" not in scope["path"]:
                headers = dict(scope.get("headers", []))
                accept_key = b"accept"
                accept_val = headers.get(accept_key, b"").decode("utf-8")
                if not accept_val or accept_val == "*/*":
                    if "stream" in scope["path"]:
                        headers[accept_key] = b"application/json, text/event-stream"
                    else:
                        headers[accept_key] = b"application/json"
                    scope["headers"] = [(k, v) for k, v in headers.items()]
        await self.app(scope, receive, send)


app = ForceAcceptJSONMiddleware(app)

if __name__ == "__main__":
    import sys
    if "--stdio" in sys.argv:
        mcp.run()
    else:
        import uvicorn
        # Allow running the server locally
        uvicorn.run("main:app", host="0.0.0.0", port=8000)
