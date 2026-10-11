import json
from unittest.mock import patch
from src.main import (
    remember,
    get_note,
    update_note,
    extract_result,
    UpdateMode,
    ERR_NOTE_NOT_FOUND,
)


def test_partial_replacement_good_examples(temp_db, mock_ollama):
    """
    Test the exact good examples from the specification:
    Original: "There is a computer who is a computer"
    1. 'computer who' / 'boy who' -> "There is a boy who is a computer"
    2. 'There' / 'Who' -> "Who is a computer who is a computer"
    """
    # 1. Setup note with the original text from user prompt
    rem_res = extract_result(remember("User Example Note", "There is a computer who is a computer"))
    note_id = rem_res["id"]
    note_data = extract_result(get_note(note_id))
    timestamp = note_data["updated_time"]

    with patch("src.main._call_node_proxy") as mock_proxy:
        mock_proxy.return_value.status_code = 200
        mock_proxy.return_value.json.return_value = {"status": "success"}

        # Good example 1: computer who / boy who
        res = extract_result(
            update_note(
                note_id=note_id,
                content="boy who",
                update_mode=UpdateMode.partial_note_replacement,
                last_modified_timestamp=timestamp,
                summary_of_changes="Replaced computer who with boy who",
                search_text="computer who",
            )
        )
        assert res.get("status") == "success"
        assert res.get("id") == note_id

        # Verify new content in DB
        updated = extract_result(get_note(note_id))
        assert updated["content"] == "There is a boy who is a computer"
        timestamp = updated["updated_time"]

        # Reset back to original
        res = extract_result(
            update_note(
                note_id=note_id,
                content="There is a computer who is a computer",
                update_mode=UpdateMode.full_note_replacement,
                last_modified_timestamp=timestamp,
                summary_of_changes="Reset to original",
            )
        )
        assert res.get("status") == "success"
        timestamp = extract_result(get_note(note_id))["updated_time"]

        # Good example 2: There / Who
        # Note: testing with prompt's update_mode="full note replacement" combined with search_text
        res = extract_result(
            update_note(
                note_id=note_id,
                content="Who",
                update_mode="full note replacement",
                last_modified_timestamp=timestamp,
                summary_of_changes="Replaced There with Who",
                search_text="There",
            )
        )
        assert res.get("status") == "success"
        updated = extract_result(get_note(note_id))
        assert updated["content"] == "Who is a computer who is a computer"


def test_partial_replacement_bad_examples(temp_db, mock_ollama):
    """
    Test the exact bad examples from the specification:
    Original: "There is a computer who is a computer"
    1. 'is a computer' / 'is a dog' -> multiple instances found
    2. 'a' / '1' -> multiple instances found
    3. 'Doggy' / 'Foobar' -> search text not found
    4. <1M chars> / 'foo' -> replace text too long
    """
    rem_res = extract_result(remember("Bad Examples Note", "There is a computer who is a computer"))
    note_id = rem_res["id"]
    timestamp = extract_result(get_note(note_id))["updated_time"]

    with patch("src.main._call_node_proxy") as mock_proxy:
        mock_proxy.return_value.status_code = 200
        mock_proxy.return_value.json.return_value = {"status": "success"}

        # Bad example 1: 'is a computer' has 2 instances
        res1 = extract_result(
            update_note(
                note_id=note_id,
                content="is a dog",
                update_mode=UpdateMode.partial_note_replacement,
                last_modified_timestamp=timestamp,
                summary_of_changes="Ambiguous replacement",
                search_text="is a computer",
            )
        )
        assert "multiple instances of `is a computer` found" in res1.get("error", "")

        # Bad example 2: 'a' has multiple instances
        res2 = extract_result(
            update_note(
                note_id=note_id,
                content="1",
                update_mode=UpdateMode.partial_note_replacement,
                last_modified_timestamp=timestamp,
                summary_of_changes="Ambiguous replacement",
                search_text="a",
            )
        )
        assert "multiple instances of `a` found" in res2.get("error", "")

        # Bad example 3: 'Doggy' not found
        res3 = extract_result(
            update_note(
                note_id=note_id,
                content="Foobar",
                update_mode=UpdateMode.partial_note_replacement,
                last_modified_timestamp=timestamp,
                summary_of_changes="Non-existent replacement",
                search_text="Doggy",
            )
        )
        assert res3.get("error") == "search text not found"

        # Bad example 4: search_text >= 1M chars
        res4 = extract_result(
            update_note(
                note_id=note_id,
                content="foo",
                update_mode=UpdateMode.partial_note_replacement,
                last_modified_timestamp=timestamp,
                summary_of_changes="Oversized search text",
                search_text="x" * 1_000_000,
            )
        )
        assert res4.get("error") == "replace text too long"

        # Content >= 1M chars
        res4b = extract_result(
            update_note(
                note_id=note_id,
                content="x" * 1_000_000,
                update_mode=UpdateMode.partial_note_replacement,
                last_modified_timestamp=timestamp,
                summary_of_changes="Oversized replacement content",
                search_text="computer",
            )
        )
        assert res4b.get("error") == "replace text too long"


def test_partial_replacement_edge_cases(temp_db, mock_ollama):
    """
    Test edge cases:
    - Empty search_text
    - Overlapping matches (e.g. 'aa' in 'aaa')
    - End of string replacement
    - Entire document replacement via search_text
    - Incompatible update_mode with search_text (append/prepend)
    - Note not found
    - Dual audience MCP annotations
    """
    rem_res = extract_result(remember("Edge Note", "aaa prefix suffix"))
    note_id = rem_res["id"]
    timestamp = extract_result(get_note(note_id))["updated_time"]

    with patch("src.main._call_node_proxy") as mock_proxy:
        mock_proxy.return_value.status_code = 200
        mock_proxy.return_value.json.return_value = {"status": "success"}

        # Empty search text
        res_empty = extract_result(
            update_note(
                note_id=note_id,
                content="foo",
                update_mode=UpdateMode.partial_note_replacement,
                last_modified_timestamp=timestamp,
                summary_of_changes="Empty search",
                search_text="",
            )
        )
        assert res_empty.get("error") == "search text cannot be empty"

        # Overlapping occurrences ('aa' occurs at 0 and 1 in 'aaa')
        res_overlap = extract_result(
            update_note(
                note_id=note_id,
                content="bb",
                update_mode=UpdateMode.partial_note_replacement,
                last_modified_timestamp=timestamp,
                summary_of_changes="Overlapping search",
                search_text="aa",
            )
        )
        assert "multiple instances of `aa` found" in res_overlap.get("error", "")

        # End of string unique match
        res_end = extract_result(
            update_note(
                note_id=note_id,
                content="new_suffix",
                update_mode=UpdateMode.partial_note_replacement,
                last_modified_timestamp=timestamp,
                summary_of_changes="Replace suffix",
                search_text="suffix",
            )
        )
        assert res_end.get("status") == "success"
        updated = extract_result(get_note(note_id))
        assert updated["content"] == "aaa prefix new_suffix"
        timestamp = updated["updated_time"]

        # Incompatible update_mode (append with search_text)
        res_incompat = extract_result(
            update_note(
                note_id=note_id,
                content="something",
                update_mode=UpdateMode.append,
                last_modified_timestamp=timestamp,
                summary_of_changes="Incompatible mode",
                search_text="prefix",
            )
        )
        assert "search_text cannot be used with append or prepend" in res_incompat.get("error", "")

        # Note not found
        res_not_found = extract_result(
            update_note(
                note_id="nonexistent-id",
                content="something",
                update_mode=UpdateMode.partial_note_replacement,
                last_modified_timestamp=timestamp,
                summary_of_changes="Note not found",
                search_text="prefix",
            )
        )
        assert res_not_found.get("error") == ERR_NOTE_NOT_FOUND

        # Test dual audience output
        raw_mcp_output = update_note(
            note_id=note_id,
            content="AAA",
            update_mode=UpdateMode.partial_note_replacement,
            last_modified_timestamp=timestamp,
            summary_of_changes="Replace aaa",
            search_text="aaa",
        )
        assert len(raw_mcp_output) == 2
        assistant_item = next(r for r in raw_mcp_output if "assistant" in r.annotations.audience)
        user_item = next(r for r in raw_mcp_output if "user" in r.annotations.audience)
        assert json.loads(assistant_item.text)["status"] == "success"
        assert f"Successfully updated note: {note_id}" in user_item.text
