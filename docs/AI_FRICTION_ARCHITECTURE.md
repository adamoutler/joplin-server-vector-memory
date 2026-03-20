# Joplin Server Vector Memory MCP: AI Interaction Friction Architecture

## 🏛️ Architectural Overview

Designing APIs and MCP tools for AI agents requires a different paradigm than designing for humans. Instead of optimizing for visual UX, we optimize for **Agentic UX**—managing the probability of an AI taking a specific action through API design. 

By implementing intentional "friction" in the MCP layer, we guide the AI towards safe, efficient behaviors while actively preventing destructive hallucinations.

This document outlines the architecture for a sliding scale of friction for the Joplin Vector Memory MCP.

---

## ⚡ Level -1: Negative Friction (Search)

**Goal:** Anticipate the AI's next step and provide the data before it asks, eliminating a costly reasoning cycle and tool call round-trip.

**Implementation Strategy:**
When an AI searches for a note, it almost always wants to read the most relevant result. Instead of returning only a list of IDs and titles (which forces the AI to make a subsequent `retrieve_note` call), we inject the full content of the top match directly into the search response.

**MCP Tool Design (`search_notes`):**
*   **Input:** `query` (string), `limit` (int, default 5)
*   **Output Behavior:**
    *   Perform hybrid/vector search.
    *   Return an array of results.
    *   For the `#1 ranked result` (if confidence score > threshold), include the `full_body` property.
    *   For results `#2 through #N`, include only `id`, `title`, and a short `snippet`.

**Example Output:**
```json
{
  "results": [
    {
      "id": "abc-123",
      "title": "Project Setup Guide",
      "score": 0.95,
      "full_body": "# Project Setup\nRun `npm install`...", // Negative friction!
      "note": "Top match full content provided."
    },
    {
      "id": "def-456",
      "title": "Old Setup Notes",
      "score": 0.65,
      "snippet": "...setup used to require..."
    }
  ]
}
```

---

## 🟢 Level 0: No Friction (Retrieve)

**Goal:** Make data access as easy and forgiving as possible.

**Implementation Strategy:**
The AI should be able to get a note if it has any reasonable identifier. The tool should be singular and straightforward.

**MCP Tool Design (`get_note`):**
*   **Input:** `identifier` (string) - Can be an exact ID, or an exact Title.
*   **Output Behavior:** 
    *   Returns the complete note object (ID, title, body, tags, timestamps).
    *   If no match, returns a clear semantic error: `"Note not found. Try searching first."`

---

## 🟡 Level 1: Low Friction (Create)

**Goal:** Encourage the AI to save thoughts and generate content without arbitrary roadblocks, while maintaining data hygiene.

**Implementation Strategy:**
Minimize required parameters. Handle complexity (IDs, parent folders, timestamps) automatically on the server side.

**MCP Tool Design (`create_note`):**
*   **Input:** 
    *   `title` (string, required)
    *   `body` (string, required)
    *   `tags` (array of strings, optional)
*   **Output Behavior:**
    *   Auto-assigns ID, current timestamp, and default notebook/folder.
    *   Returns the new `id` and a success confirmation.

---

## 🟠 Level 2: Medium Friction (Update)

**Goal:** Prevent blind overwrites, accidental data loss from truncated context windows, and ensure the AI knows exactly what it is changing.

**Implementation Strategy:**
Implement **Optimistic Concurrency Control (OCC)** and require explicit modification instructions. The AI cannot update a note unless it proves it has seen the latest version.

**MCP Tool Design (`update_note`):**
*   **Input:**
    *   `id` (string, required)
    *   `content` (string, required)
    *   `update_mode` (enum: `append` | `full_replace`, required) - Forces the AI to declare intent.
    *   `last_modified_timestamp` (integer/string, required) - The AI must provide the exact timestamp of the note it is trying to edit.
    *   `summary_of_changes` (string, required) - Forces the AI to rationalize its edit (Chain of Thought prompt engineering built into the API).
*   **Output Behavior:**
    *   If `last_modified_timestamp` does not match the server's current timestamp, reject with: `"Error: Note has been modified since you last read it. Retrieve the note again before updating."`
    *   If valid, apply the update and return the new timestamp.

---

## 🔴 Level 3: Extreme Friction (Delete)

**Goal:** Mathematically minimize the risk of accidental or hallucinated deletion by forcing a multi-turn, cryptographic verification process combined with a psychological "Safety Attestation."

**Implementation Strategy:**
Make deletion impossible with a single tool call. Force a "Request -> Verify -> Execute" loop. This acts as a cognitive speed bump for the LLM. Furthermore, require the LLM to explicitly type out a destructive confirmation, triggering its safety alignment weights.

**MCP Tool Design (Two-Tool System):**

1.  **Tool 1: `request_note_deletion`**
    *   **Input:** `id` (string, required), `reason` (string, required)
    *   **Action:** Does *not* delete the note.
    *   **Output:** Returns a temporary, cryptographic `deletion_token` (e.g., `"DEL-9x8F2-A1B2"`) and instructions: *"To permanently delete note '{title}', you must call `execute_deletion` with this token and complete the safety attestation."*

2.  **Tool 2: `execute_deletion`**
    *   **Input:** 
        *   `deletion_token` (string, required)
        *   `confirm_title` (string, required) - AI must type the exact title of the note it is deleting.
        *   `safety_attestation` (object, required) - A mandatory checklist object containing:
            *   `content_hash`: (string, required) - You must provide the cryptographic `content_hash` that was returned when you retrieved or searched for this note. This mathematically proves you have accessed the target data.
            *   `confirmation_statement`: (string, must exactly match: "I confirm the user explicitly requested the permanent, irreversible destruction of this note, and I understand this data cannot be recovered.")
    *   **Action:** Validates the token, the title match, ensures the `content_hash` exactly matches the SHA-256 hash of the current note body, and ensures the confirmation statement is strictly correct. If valid, executes a soft-delete (moves to trash) or hard-delete based on system policy.
    *   **Output:** Deletion confirmation.

### Why Extreme Friction Works on LLMs:
1.  **Breaks Hallucinations:** If an LLM hallucinates a command to delete, it will fail because it cannot guess the cryptographic `deletion_token` or the `content_hash`.
2.  **Forces Chain of Thought:** To execute the second step, the LLM must persist its intention across multiple turns of conversation.
3.  **Cryptographic Proof of Retrieval:** By requiring the `content_hash`, the server mathematically guarantees that the AI has recently requested the full note data via `get_note` or `search_notes` and hasn't just guessed an ID.
4.  **Safety Alignment Activation:** Forcing the LLM to generate the tokens "irreversible destruction" and "cannot be recovered" heavily activates its internal safety guardrails, causing it to pause and ensure the user actually requested this.