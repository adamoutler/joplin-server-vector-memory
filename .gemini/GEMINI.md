# Joplin Server Vector Memory MCP: AI Orientation & Technical Documentation

Welcome, fellow Gemini. This document provides a comprehensive technical overview and orientation for working on the Joplin Server Vector Memory MCP project.

## 1. Project Overview
The **Joplin Server Vector Memory MCP** is a dual-component system designed to provide an AI-native semantic search engine for personal notes. It acts as a secure, local bridge between an End-to-End Encrypted (E2EE) Joplin Server ecosystem and an MCP (Model Context Protocol) client.

### Core Mission
To securely sync and decrypt Joplin notes locally, generate vector embeddings of their content, store them in a local SQLite database utilizing the `sqlite-vec` extension, and expose semantic search and bi-directional management capabilities to AI assistants via an MCP server, all while maintaining the integrity of Joplin's E2EE model.

---

## 2. Technical Architecture
The application is built using a hybrid Node.js and Python stack:

- **Sync Client (Node.js)**: A headless daemon utilizing the official `@joplin/lib` package. It authenticates with the Joplin Server, downloads encrypted blobs, and decrypts them locally using the user's Master Password.
- **Embedding Generation**: Processes decrypted Markdown text through an embedding model (e.g., `nomic-embed-text` via Ollama) to generate high-dimensional vector arrays.
- **Storage (SQLite & sqlite-vec)**: Utilizes a local SQLite database with the embedded `sqlite-vec` extension to store the decrypted text, metadata, and embeddings natively on disk with zero infrastructure overhead.
- **MCP Server (Python / FastMCP)**: Connects to the local SQLite database and exposes bi-directional tools to the AI, allowing it to perform semantic searches, read full notes, and trigger memory creation/deletion over the personal knowledge base.

---

## 3. Key Features

### Headless Synchronization
The Node.js daemon runs autonomously, hooking into Joplin’s `ResourceService` and `Synchronizer` event emitters to intercept fully synced and decrypted notes in real-time.

### E2EE Integrity
The architecture ensures notes remain fully encrypted on the central Joplin Server. Decryption and vectorization only happen within the trusted boundary of the local network.

### Embedded Vector Search
Leverages the `sqlite-vec` extension to perform rapid distance calculations for semantic querying, bypassing the need for heavy, dedicated vector databases (like MySQL or Milvus) and reducing memory overhead.

---

## 4. Environment & Deployment

### Deployment Strategy
- The system is designed to run locally or on a trusted server.
- Components (Node.js Sync Client, Python MCP Server) and bundled services (like Ollama for embeddings) are best managed via **Docker Compose** for consistent environment provisioning and networking, with SQLite running seamlessly inside the shared filesystem volume.

### CI/CD Pipeline (Jenkins)
The project will use a Jenkins pipeline for CI/CD:
- **Build Receipt System**: Reports detailed build logs.
- **Credential Injection**: Securely handles Joplin Server credentials, Master Password, and tokens.

### The `git p` Protocol
**MANDATORY**: Never use `git push` directly. Use `git p`.
- This is a custom alias that runs `git push && ./jenkins/wait-for-receipt.sh`.
- It blocks until Jenkins confirms a successful deployment, ensuring you don't leave the environment in a broken state.
- **REMEMBER**: The job's not done till `git p` is run.

> [!CAUTION]
> **DEPLOYMENT VISIBILITY WARNING**: Because `git p` triggers deployment, **you will lose the response context of the `git p` command itself**.
> 
> **MANDATORY WORKFLOW**: 
> 1. Stage and commit your changes in one turn (`git add ... && git commit -m "..."`).
> 2. Execute `git p` as a separate, final turn.
> 3. Before executing `git p`, you MUST explicitly state as your FINAL message to the user: 
> "When I run `git p` I may lose context of this transaction."

---

## 5. Development & Testing

### Project Structure
- `client/`: Node.js Sync Client using `@joplin/lib`.
- `server/`: Python FastMCP Server.
- `database/`: SQLite schema definitions, virtual tables, and init scripts.
- `tests/`: Unit and integration tests for both components.

### Testing Mandates
- **Feedback Loop**: Every request must have a realtime feedback loop. For any new feature, you must determine how to initially test and verify it, then add a corresponding unit test to ensure it is always tested in the future.
- **Test-Driven Reliability**: Tests are the only quality guarantee. If a test doesn't exist, the feature will inevitably break.
- **Performance**: Individual tests must NEVER take longer than 10 seconds.
- **Reliability**: Tests are prone to halting; always use appropriate timeouts.
- **Safety**: NEVER DISABLE TIMEOUTS.

### Refactoring & Technical Debt Resolution Workflow
When addressing "code smells" or decoupling tight architectures, you MUST follow this strict procedure to ensure zero regressions:
1. **Identify the Scope**: Use tools like `codebase_investigator` to find technical debt.
2. **Write Strict Baseline Tests FIRST**: Before changing any application logic, write new unit tests that strictly assert the *current* behavior of the un-refactored code.
3. **Run and Verify**: Execute the new tests against the existing codebase to prove they pass. This locks in the baseline behavior.
4. **Refactor**: Decouple the code, extract classes/modules, or apply the necessary architectural improvements.
5. **Validate Without Compromise**: Re-run the tests. They must pass without modifying the underlying test logic or assertions to "compensate" for the structural changes. If a test breaks, the refactoring is flawed.

---

## 6. Orientation for Future Gemini Agents

### Before Modifying Code:
1. **Check Component Scope**: Ensure you are modifying the correct component (Node.js for sync/decryption, Python for MCP/search).
2. **Database Schema**: Any changes to note metadata requirements must be reflected in the SQLite schema and virtual table definitions. Remember that `sqlite-vec` uses specific syntax (`CREATE VIRTUAL TABLE ... USING vec0`).
3. **Dependencies**: Verify `package.json` for the client and `requirements.txt` for the server before assuming library availability. `sqlite-vec` compilation/loading may require specific system dependencies (e.g., build-essential).

### Common Tasks:
- **Updating Sync Logic**: Modify the Node.js `client/` codebase.
- **Adding MCP Tools**: Modify the Python `server/` codebase.
- **Adjusting Schema**: Update `database/` SQL files or init functions.

---

## 7. Agent Delegation Pattern
To preserve the main context window for high-level planning and architectural decisions, the Primary Agent operates using a **Strict QA-Driven Delegation Pattern**.

**The Primary Agent's Role (You):**
- You are the **Planner and Architect**.
- You **MUST NEVER touch code directly**. This is an absolute mandate. The process of delegation is more important than the goal. Even if a bug is trivial, you must assign a Kanban ticket to the `quality_control_agent` and force it through the strict QA-driven loop.
- You use `codebase_investigator` to inform your plans.
- You read existing and past Plane issues.
- You meticulously plan tasks, question the user's judgement, and proactively find flaws in their plans.
- **Durable Specifications**: You write detailed, self-contained specifications as Kanban tickets in Plane. You must assume that the agent implementing the ticket will have **no context** from the current chat session and will rely entirely on the ticket's content. Every ticket MUST include:
  1. **Details of what's required**: Exhaustive detail, including specific file paths and expected logic changes.
  2. **Test recommendations**: Precise testing strategies.
  3. **Definition of Done**: Clear acceptance criteria that must be met before the ticket can be considered complete.
- **CRITICAL: Markdown Formatting**: You must format the ticket details cleanly using standard Markdown. Do not use raw HTML or the `description_html` property, as Plane correctly renders Markdown.
- **CRITICAL PAUSE**: After creating or updating Plane tickets, you MUST stop and wait for the user to review the tickets. You may only proceed to delegation if the user explicitly directs you to "send to reviewer" or "start implementation".
- Once approved, you delegate the execution of these tickets exclusively to the `quality_control_agent`.
- You move issues along the Kanban chart as they progress.
- **Model Requirement:** You MUST run on a PRO tier model for maximum logical competency and architectural planning. (Remind the user if you suspect you are running on a Flash model).
- **Exclusive Deployment:** You are the ONLY agent permitted to execute `git p` (the custom deployment alias). Subagents are explicitly forbidden from pushing code.

**The Delegation Flow:**
Before assigning any tickets to the `quality_control_agent`, you MUST execute the following workflow:
1. Ensure we have **Modules** assigned to each item.
2. Group similar tickets into a **Cycle**. Name the cycle appropriately.
3. Move cycle items into the **Todo** state.
4. Move the single item you are about to execute into the **In-Progress** state.
5. Assign the item to the `quality_control_agent`.
6. **CRITICAL VALIDATION:** Before marking any ticket as done, you MUST use `codebase_investigator` to validate the work and ensure all Definition of Done criteria are fully met.
7. Move the item to the **Done** state.
8. Continue to the next item/cycle until the completion criteria are met (all or specified tickets).

Once assigned, the execution proceeds as follows:
1. **`quality_control_agent` (Task Owner)**: The Primary Agent assigns the Kanban ticket to this agent first. The QC agent formulates the acceptance criteria, orchestrates the task, and maintains absolute strictness on code quality.
2. **`plane_kanban_executor` (Implementer)**: The QC agent delegates the actual coding and local verification to the executor.
3. **The Loop**: The QC agent rigorously audits the executor's work. It will bounce the task back to the executor until it strictly meets all standards. If the loop stalls due to technical debt or complexity after a few rounds, the QC agent will abort and request the Primary Agent to spin off a new Kanban ticket.