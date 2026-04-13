# Root Module (/)

## How it works
This is the root module of the Joplin Server Vector Memory MCP project. It orchestrates the dual-component architecture consisting of a Node.js Sync Client (`client/`) and a Python MCP Server (`server/`). It defines the Docker Compose configurations (`docker-compose.yml`, `docker-compose.auth.yml`, `docker-compose.test.yml`), CI/CD pipelines (GitHub Actions, Jenkinsfile), and high-level project documentation.

## Dependencies
- Docker
- Docker Compose
- Git
- CI/CD tools (GitHub Actions, Jenkins)

## What depends on it
The entire application relies on the root directory's Docker configuration to provision the environment, mount shared volumes (like the SQLite database), and handle networking between the Node.js and Python containers.