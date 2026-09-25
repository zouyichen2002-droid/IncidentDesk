#!/bin/sh
set -eu
# Isolated test database. Application data is untouched.
docker compose exec -T postgres psql -U postgres -d postgres -tc "select 1 from pg_database where datname='incident_test'" | rg -q 1 || docker compose exec -T postgres createdb -U postgres incident_test
docker compose exec -T postgres sh -c 'pg_dump -U postgres -d incidentdesk --schema-only --schema=business | psql -U postgres -d incident_test' > /tmp/incident-test-schema.log 2>&1
docker compose exec -T postgres psql -U postgres -d incident_test -c "insert into business.members values('alice','orders','approver') on conflict do nothing; insert into business.services values('svc-17','orders','Orders','local/test',1,true) on conflict do nothing" >/dev/null
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d incident_test < db/migrations/003_search.sql >/dev/null
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d incident_test < db/migrations/004_queries.sql >/dev/null
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d incident_test < db/migrations/005_conversation.sql >/dev/null
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d incident_test < db/migrations/006_conversation_sessions.sql >/dev/null
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U postgres -d incident_test < db/migrations/007_conversation_context_reset.sql >/dev/null
cd backend
TEST_DATABASE_URL='postgres://incident_api:local-api@localhost:55432/incident_test?search_path=business' go test -race -count=1 -v ./...
go vet ./...
