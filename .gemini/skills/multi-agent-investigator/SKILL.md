---
name: multi-agent-investigator
description: Orchestrates a multi-step investigation using specialized agents to find deep codebase problems. Use this when you need a comprehensive quality and security audit on a specific inquiry.
---

# Multi-Agent Investigator

This skill guides you through a rigorous, multi-step investigation of a codebase. It leverages multiple specialized sub-agents to analyze code quality, security implications, and deeply investigate a specific inquiry. 

By separating the investigation into discrete steps and passing the context between specialized agents, this process uncovers problems that traditional, single-pass inquiries often miss.

## The Workflow

When a user triggers this skill with an inquiry (e.g., "Investigate the authentication middleware"), follow these exact steps sequentially. Do not combine these steps into a single tool call; execute them one by one to ensure deep reasoning and context building.

Before starting, create a temporary directory to store the investigation artifacts. For example: `mkdir -p .gemini/tmp/investigation`.

### Step 1: Baseline Quality Report
Ask the `codebase_investigator` agent to generate a general code quality and problems report for the relevant area of the codebase.
*   **Action:** Call the `codebase_investigator` tool.
*   **Prompt:** "Generate a comprehensive code quality and potential problems report for [insert relevant files/directories based on the user's inquiry]. Do not focus on the specific inquiry yet; just establish the general baseline quality and identify any immediate code smells."
*   **Output:** Save the full response to `.gemini/tmp/investigation/1.md`.

### Step 2: Specific Inquiry Investigation
Ask the `codebase_investigator` agent to deeply analyze the user's specific inquiry.
*   **Action:** Call the `codebase_investigator` tool.
*   **Prompt:** "Investigate the following inquiry: [insert user's exact inquiry]. Focus specifically on the architecture, logic, and potential flaws related to this feature."
*   **Output:** Save the full response to `.gemini/tmp/investigation/2.md`.

### Step 3: Security Engineer Follow-up
Read `1.md` and `2.md`. Pass this context to the `security-engineer` agent to review the findings and generate a list of critical follow-up questions.
*   **Action:** Call the `security-engineer` tool.
*   **Prompt:** "Review the following baseline code quality report:\n\n[contents of 1.md]\n\nAnd the specific investigation report:\n\n[contents of 2.md]\n\nBased on these findings, what are the most critical follow-up questions, security concerns, logical gaps, or edge cases we need to look into?"
*   **Output:** Save the response to `.gemini/tmp/investigation/3.md`.

### Step 4: Specialized Engineering Report
Identify the "best engineer for the job" from your available sub-agents based on the domain of the inquiry (e.g., `backend-architect` for APIs, `frontend-developer` for UI, `ai-engineer` for ML models, `devops-automator` for infrastructure). Ask this specialized agent to answer the questions raised by the security engineer.
*   **Action:** Call the chosen specialized agent tool.
*   **Prompt:** "Review the previous reports and the security follow-up questions:\n\n[contents of 1.md]\n[contents of 2.md]\n[contents of 3.md]\n\nPlease investigate the codebase to answer the follow-up questions from the security engineer. Provide a final, comprehensive report on your findings."
*   **Output:** Save the response to `.gemini/tmp/investigation/4.md`.

### Step 5: Final Validation
Ask the same specialized engineer (or a dedicated testing agent like `testing-reality-checker` or `evidence-collector`) to validate the final findings.
*   **Action:** Call the chosen validation agent tool.
*   **Prompt:** "Review the final engineering report:\n\n[contents of 4.md]\n\nValidate these findings against the current state of the codebase. Are there any discrepancies, false positives, or recommendations that require immediate action? Provide a final verdict."
*   **Output:** Present this final validation summary to the user.

## Important Directives
*   **Patience:** Take your time. Each step must be fully completed and written to its respective markdown file before proceeding to the next step.
*   **Persistence:** Always use `write_file` to save the intermediate steps (`1.md`, `2.md`, `3.md`, `4.md`). This builds the necessary context for the downstream agents.
*   **Transparency:** Inform the user briefly about which step you are currently executing. Do not work in silence for the entire workflow.