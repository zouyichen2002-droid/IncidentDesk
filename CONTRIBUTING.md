# Contributing

Issues and pull requests are welcome. Describe the question, expected result, actual result, and a minimal reproduction. Remove API keys, tokens, private logs and personal data before posting.

## Development

See README for local deployment. Keep `.env` private; use `.env.example` for configuration names. The demo accounts and fixed local credentials are intentional fixtures and must not be used for internet-facing production deployments.

Relevant checks:

```sh
./scripts/test-go.sh
(cd worker && uv run pytest -q)
(cd query && uv run python -m unittest discover -s tests -v)
(cd web && npm ci && npm run build)
docker compose config --quiet
```

The Go script uses a separate `incident_test` database and needs the local PostgreSQL service. Model-dependent acceptance scripts require your own Mistral key and may incur provider charges. Do not run destructive fixture or load scripts against production data.

Add regression coverage for behavioral changes. For SQL results, compare with an independent expected query; for ranking, check row order as well as values. Record dataset size and test environment. Do not turn a local test pass into a production-quality or arbitrary-language accuracy claim.

Keep upstream notices and licenses intact. Contributions to original project code are submitted under the project's MIT license.
