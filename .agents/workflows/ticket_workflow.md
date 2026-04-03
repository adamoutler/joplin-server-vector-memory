---
description: "How to complete or create tickets"
---

# Ticket Workflow Instruction

As a Gemini agent working on this directory, your primary goal is to **complete or create tickets**. 

Whenever you finish working on an issue, you MUST use the automated script to complete the ticket. Do NOT use standard MCP kanban tools to transition a ticket to "Done".

Follow these specific steps to close tickets:

1. Ensure your repository working tree is completely clean. Code must be fully committed.
2. Ensure you have pushed your branch to origin.
// turbo
3. Run the ticket completion script:
   ```bash
   ./scripts/complete_work.sh <TICKET-ID>
   ```
4. If the completion script returns a "NEEDS WORK" result, read the feedback directly in the script output, make any necessary adjustments or documentation, push again, and re-run the script.
