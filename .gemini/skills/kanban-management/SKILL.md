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

-   **Mandatory Architecture Pre-computation:** Before writing a ticket, you MUST pass the user's high-level request to an architect agent (e.g., `ux-architect`, `backend-architect`, or `project-manager-senior`) to investigate the codebase and draft the strict Kanban specification. Do not guess at the implementation details yourself. If a user requests changes or additions to a ticket, consider passing the ticket back to the relevant expert architect to ensure the technical integrity of the modifications.
-   **Do not execute code directly:** Your role is to plan, create robust tickets, and delegate them to the appropriate **specialized execution agent** (e.g., `frontend-developer`, `backend-architect`, `devops-automator`) based on the ticket's domain.
-   **Review Required:** After creating or updating tickets, pause and await user approval before assigning them for execution.
-   **Validation Before Closure:** Never move a ticket to "Done" without assigning it to a **specialized QA agent** (e.g., `evidence-collector`, `test-results-analyzer`, `api-tester`) to empirically verify that all criteria in the Definition of Done have been strictly met. 
-   **The Final Reality Check:** As the absolute last step before closing a ticket, you MUST run the `reality-checker` agent. This agent defaults to "NEEDS WORK" and requires overwhelming, concrete proof (such as screenshots, logs, or command outputs) that the change is production-ready. You may need to run this check 3-4 times, passing it new evidence each time, until it provides an explicit passing certification.

---

> **CRITICAL REMINDER:** Before proceeding with major architectural plans, executing the `git p` deployment protocol, or utilizing the QA delegation pattern, you MUST read the project's foundational guidelines.
> 
> 👉 **Read the `.gemini/GEMINI.md` file for essential technical orientation, architecture details, and strict deployment mandates.**