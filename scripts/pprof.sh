#!/bin/sh
set -eu
mkdir -p .local
curl -fsS 'http://127.0.0.1:6060/debug/pprof/profile?seconds=20' -o .local/cpu.prof
go tool pprof -top .local/cpu.prof > docs/evidence/pprof-top.txt
curl -fsS 'http://127.0.0.1:6060/debug/pprof/goroutine?debug=1' -o docs/evidence/goroutines.txt
docker compose exec -T postgres psql -U postgres -d incidentdesk -c "EXPLAIN (ANALYZE,BUFFERS) SELECT id FROM business.investigations WHERE team='orders' ORDER BY created_at DESC,id LIMIT 50" > docs/evidence/query-plan.txt
