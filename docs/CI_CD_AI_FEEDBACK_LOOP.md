# CI/CD and AI Feedback Loop Architecture

This document outlines the Continuous Integration and Continuous Deployment (CI/CD) system used in the Joplin Server Vector Memory MCP project, with a specific focus on how it integrates with AI agents to provide immediate, actionable feedback during the development lifecycle.

## Overview

The repository utilizes **GitHub Actions** for its CI/CD pipeline. The primary goals of this pipeline are to ensure code quality, verify system behavior through automated tests, build deployment artifacts, and crucially, **feed error logs back to the developer or AI agent** autonomously without requiring manual inspection of the GitHub UI.

## 1. GitHub Actions Pipeline (`.github/workflows/ci.yml`)

The pipeline triggers on `push` and `pull_request` events targeting the `main` branch. It consists of the following primary jobs:

### A. Linting (`lint`)
Ensures code adheres to style guidelines before running expensive tests.
*   **Node.js**: Runs ESLint (`npm run lint`) for the client.
*   **Python**: Runs Flake8 (`flake8 .`) for the server.

### B. Node.js Tests (`test-node`)
Runs unit and integration tests for the JavaScript/Node.js client daemon.
*   Executes Jest tests using a matrix strategy across Node.js versions 20 and 22.
*   Generates and uploads JUnit test result XML artifacts.

### C. Python Tests (`test-python`)
A comprehensive testing suite for the Python FastMCP server and end-to-end integration. Runs across Python 3.11 and 3.12.
*   **Unit Tests**: Core server logic, configuration, OpenAPI, and database schema tests.
*   **Core API & E2E**: Spins up an ephemeral Joplin instance via Docker Compose (`docker-compose.test.yml`) and tests the complete lifecycle (syncing, vectorizing, MCP endpoints).
*   **Live API**: Tests against the active endpoints.
*   **Auth Flow & UI**: Uses Playwright to test the dashboard authentication flow (`docker-compose.auth.yml`).
*   **Artifacts**: Automatically extracts and uploads Playwright traces, screenshots, video recordings, and Docker logs if failures occur.

### D. Reporting & Deployment
*   **Publish Test Results (`publish-test-results`)**: Parses the JUnit XML artifacts and publishes them directly to PRs as checks using `EnricoMi/publish-unit-test-result-action`.
*   **Build Container (`build-container`)**: On successful merges to `main`, builds the complete Docker image and pushes it to the GitHub Container Registry (`ghcr.io`).

---

## 2. The AI Feedback Loop: `git p` Wrapper

The most critical component for AI agents working in this repository is the `git-p.sh` script, aliased as `git p`. 

When an AI agent (like Gemini CLI) modifies code and pushes it, standard behavior leaves the agent blind to the CI results. To fix this, the repository mandates using `git p` for pushing changes.

### How it works:
1.  **Push**: The script performs a standard `git push`.
2.  **Tracking**: It retrieves the commit SHA and uses the GitHub CLI (`gh`) to poll the API until it identifies the resulting GitHub Action Run ID.
3.  **Waiting**: It continuously monitors the run's status, blocking the terminal.
4.  **Feedback Delivery (The Magic)**:
    *   If the CI run **succeeds**, the script exits cleanly, and the AI agent knows its task was perfectly validated.
    *   If the CI run **fails**, the script executes `gh run view "$RUN_ID" --log-failed | tail -n 200`.
5.  **Agent Consumption**: This pipes the exact failure logs (e.g., specific Pytest assertion errors, ESLint syntax complaints) directly into standard output. 

### Why this is important for AI Agents:
When an AI agent uses `run_shell_command("git p")`, the agent will be suspended until the CI completes. If it fails, the agent will receive the error logs natively within its terminal context. This allows the AI agent to immediately enter an autonomous **Plan -> Act -> Validate** debugging cycle. It can read the error, adjust the code, and run `git p` again without any human intervention.

## Usage for Agents

*   **Setup**: Ensure the alias is active: `git config alias.p '!bash scripts/git-p.sh'`
*   **Execution**: Never use `git push`. Always execute your commits with `git p`.
*   **Dependencies**: Requires `gh` (GitHub CLI) installed and authenticated (`gh auth login`).