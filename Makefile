.PHONY: up test eval helm down
up:
	./scripts/deploy-local.sh
test:
	./scripts/test-go.sh
	cd worker && uv run pytest -q
	cd web && npm run build
	uv run --project worker python scripts/smoke.py
eval:
	uv run --project worker python scripts/evaluate.py
helm:
	helm lint deploy/helm/incidentdesk
	helm template incidentdesk deploy/helm/incidentdesk
down:
	docker compose down
