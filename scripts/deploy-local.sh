#!/bin/sh
set -eu
CODE_VERSION=$(git rev-parse HEAD)
export CODE_VERSION
docker compose up -d --wait postgres
# Init scripts handle an empty database; additive migrations also apply to existing volumes.
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d incidentdesk < db/migrations/002_runtime.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d incidentdesk < db/migrations/003_search.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d incidentdesk < db/migrations/004_queries.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d incidentdesk < db/migrations/005_conversation.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d incidentdesk < db/migrations/006_conversation_sessions.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d incidentdesk < db/migrations/007_conversation_context_reset.sql
docker compose up -d --build --wait --wait-timeout 180
docker compose exec -T query python -m app.scripts.initialize
docker compose up -d --scale worker=3 worker
printf 'Workbench: http://localhost:8088\nAPI: http://localhost:8080\nGrafana: http://localhost:3000\n'
