#!/bin/bash
set -e

echo "1. Standing up Postgres and Joplin Server..."
docker network create joplin-net || true
docker run -d --name joplin-db --network joplin-net -e POSTGRES_USER=joplin -e POSTGRES_PASSWORD=joplin -e POSTGRES_DB=joplin -v joplin-data:/var/lib/postgresql/data postgres:16 || true

docker run -d --name joplin-server --network joplin-net -p 22300:22300 -e APP_BASE_URL=http://joplin-server:22300 -e APP_PORT=22300 -e DB_CLIENT=pg -e POSTGRES_PASSWORD=joplin -e POSTGRES_DATABASE=joplin -e POSTGRES_USER=joplin -e POSTGRES_PORT=5432 -e POSTGRES_HOST=joplin-db joplin/server:latest || true

echo "Waiting for Joplin Server to be ready..."
sleep 15
until curl -s -H "Host: joplin-server:22300" http://localhost:22300/api/ping > /dev/null; do
    echo "Waiting for Joplin Server..."
    sleep 2
done
echo "Joplin Server is up."

echo "2. Standing up the MCP app (no env vars)..."
cat << 'YML' > docker-compose.repro.yml
services:
  app:
    build: .
    ports: ["3000:3000", "8000:8000"]
    volumes: ["./repro_data:/app/data"]
    networks: ["joplin-net"]
networks:
  joplin-net:
    external: true
YML

rm -rf repro_data && mkdir -p repro_data
docker compose -f docker-compose.repro.yml up -d --build
sleep 5
until curl -s http://localhost:3000/llms.txt > /dev/null; do
    echo "Waiting for MCP App..."
    sleep 2
done

echo "3. Marrying container via /auth..."
# We use setup:1-mcp-server
curl -s -X POST http://localhost:3000/auth \
  -u "setup:1-mcp-server" \
  -H "Content-Type: application/json" \
  -d '{"serverUrl": "http://joplin-server:22300", "username": "admin@localhost", "password": "admin", "memoryServerAddress": "http://localhost:3000"}'

echo -e "\n\n4. Verifying login with User credentials..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -u "admin@localhost:admin" http://localhost:3000/status)
echo "Attempt 1 HTTP Code: $HTTP_CODE"

echo "5. Restarting MCP app..."
docker compose -f docker-compose.repro.yml restart app
sleep 10
until curl -s http://localhost:3000/llms.txt > /dev/null; do sleep 1; done

echo "6. Verifying login again..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -u "admin@localhost:admin" http://localhost:3000/status)
echo "Attempt 2 HTTP Code: $HTTP_CODE"

echo "Node logs:"
docker compose -f docker-compose.repro.yml logs --tail=30 app

echo "Cleaning up..."
docker compose -f docker-compose.repro.yml down -v
docker rm -f joplin-server joplin-db
docker volume rm joplin-data
docker network rm joplin-net
