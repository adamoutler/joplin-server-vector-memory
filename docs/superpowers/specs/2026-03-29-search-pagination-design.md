# Search Pagination Design (JOPLINMEM-168)

## Overview
Implement pagination for the `notes.search` tool to allow AI agents to browse through search results in chunks. This implementation uses Reciprocal Rank Fusion (RRF) to combine results from Vector and FTS sources.

## Core Requirements
- Support `page` and `limit` parameters in `notes.search`.
- Maintain RRF ranking accuracy across pages.
- Efficiently manage LLM context window by selectively injecting `full_body`.

## Technical Specification

### 1. Tool Signature Update
```python
@mcp.tool(name="notes.search")
def search_notes(query: str, page: int = 1, limit: int = 5) -> list[dict]:
    """
    Search notes semantically using the provided query with pagination.
    Returns a list of notes with their ID, Title, and a Blurb.
    """
```

### 2. Candidate Pool Logic
To ensure top results are not lost due to pagination, we fetch a larger candidate pool from each database source before RRF calculation.
- **Vector Search (KNN)**: Set `k = 100`.
- **FTS Search (BM25)**: Set `LIMIT 100`.

This pool of up to 200 candidates is merged and ranked in memory using the RRF formula:
`score(d) = sum(1.0 / (rank(d, s) + 60) for s in sources)`

### 3. Pagination & Slicing
The ranked list is sliced using standard 1-based page math:
```python
start = (page - 1) * limit
end = start + limit
paged_results = all_ranked_results[start:end]
```

### 4. Full Body Injection Strategy
- **Rule**: `full_body` is only included for the **first result** of the **first page**.
- **Reasoning**: This provides immediate context for the most relevant result while keeping subsequent pages or lower-ranked results lightweight for the LLM context.

### 5. Error Handling
- If `page < 1`, default to `page = 1`.
- If `limit < 1` or `limit > 50`, default to reasonable bounds (e.g., `limit = 5`).
- Handle empty results gracefully (return `[]`).

## Testing & Verification

### Unit Tests (`server/tests/test_search_pagination.py`)
- **`test_pagination_slices`**: Verify `page=1, limit=5` returns the first 5 results and `page=2, limit=5` returns the next 5.
- **`test_full_body_injection`**: Verify `full_body` key exists on result `[0]` of page 1, but is absent on result `[0]` of page 2 and result `[1]` of page 1.
- **`test_candidate_pool_depth`**: Verify results are correctly ranked even if they are not in the top 5 of one of the sources but rank high after fusion.

### Acceptance Criteria (Definition of Done)
- [ ] `notes.search` tool accepts `page` and `limit`.
- [ ] Results are accurately ranked using RRF from a 100-item candidate pool per source.
- [ ] Pagination returns distinct, non-overlapping slices of the ranked results.
- [ ] `full_body` is only injected for the top-ranked result on the first page.
- [ ] All search-related tests pass.
