---
name: kanban-management
description: Essential guidelines and strict criteria for creating, updating, and managing Kanban tickets effectively within the project. Trigger this skill before any significant interaction with the issue tracker.
---

# Kanban Management Skill

This skill outlines the strict requirements for creating, updating, and managing Kanban tickets. As the primary orchestrator, you must adhere to these rules to ensure clarity, strict quality control, and proper delegation to the execution agents.

## Core Directives for Kanban Management

1.  **Exhaustive Detail:** Tickets must be self-contained. The agent executing the ticket will have NO context from the main chat session. You must include explicit file paths, precise logic requirements, and clear bug descriptions.
2.  **Strict Definition of Done (DoD):** Never close a ticket without a clearly defined, empirically testable Definition of Done. The DoD must state exactly what constitutes success (e.g., "curl http://localhost:3000/docs returns an HTTP 200"). Vague criteria like "the bug is fixed" are unacceptable.
3.  **Mandatory Test Recommendations:** Every ticket must explicitly demand test creation or modification to prevent regressions. Specify the type of test (unit, integration, E2E) and the file to modify.
4.  **Formatting:** Always use standard Markdown (`description_html` property). 
5.  **Strict Heading Rule:** The FIRST line of the description MUST be plain text or bold text. Do not start the description with a heading (e.g., `### Details`), as the ticket title already serves as the top-level heading. Headings may be used *after* the initial paragraph.

## Ticket Referencing

Users may refer to tickets using the format `[Project Identifier]-[Sequence ID]` (e.g., `JOPLI-32`). You can use the `retrieve_work_item_by_identifier` tool with the `project_identifier` ("JOPLI") and `issue_identifier` (32) to fetch these tickets directly without needing the UUID.

## Ticket Structure Template

When creating or updating a ticket, ensure it follows this general structure, ensuring no heading is at the very top:

```markdown
**Context/Reason:** [Brief explanation of why this ticket exists, or reason for reopening if applicable.]

[Clear, exhaustive explanation of the problem or feature...]

**Files to modify:**
* `path/to/file.ext`: [Specific instructions for this file]

### Test Recommendations
* [Specific test case to write or update to verify this change]

### Definition of Done
* [Strict, testable criteria 1]
* [Strict, testable criteria 2]
```

## Workflow & Delegation

-   **Do not execute code directly:** Your role is to plan, create robust tickets, and delegate them to the `quality_control_agent`.
-   **Review Required:** After creating or updating tickets, pause and await user approval before assigning them for execution.
-   **Validation Before Closure:** Never move a ticket to "Done" without empirically verifying that all criteria in the Definition of Done have been strictly met (e.g., via `codebase_investigator` or explicit test results).

---

> **CRITICAL REMINDER:** Before proceeding with major architectural plans, executing the `git p` deployment protocol, or utilizing the QA delegation pattern, you MUST read the project's foundational guidelines.
> 
> 👉 **Read the `.gemini/GEMINI.md` file for essential technical orientation, architecture details, and strict deployment mandates.**