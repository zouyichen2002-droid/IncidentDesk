# Add a connector or skill

Implement `capabilities`, `discover`, `health`, and `query(runtime, step, cursor)` and register an instance with `connectors.register`. Query must ask `runtime.authorize(tool)` before any source access, push down the server-provided service/time scope, return stable record IDs, event/observation times, locator, version, deleted marker and explicit continuation. Do not claim source ACL synchronization when only connection-level grants exist.

`DeploymentSource` demonstrates parameterized SQL with a SELECT-only role. `HTTPSource` demonstrates bounded HTTP, transient retry and circuit opening. Logs use a monotonic ID; Git and Markdown explicitly rescan versioned controlled sources. Source mutation notifications advance the Go service watermark; never silently reuse old cached contexts after mutation.

The query executor dispatches through the registry. A new source/object still requires adding its allowed type/path to the finite ontology/schema and an explicit Go tool allowlist grant; registration alone deliberately does not authorize a tool. `test_connector_contract_extension` shows a minimal connector contract test without changing executor source branches.

Skills are reviewed versioned manifests in `gateway.SKILLS`. `log-analysis@1` can read only logs; `release-compare@1` can read only deployments and Git. The MCP SDK process exposes only `analyze_logs`, with bounded snapshot input. Discovery schemas and tool versions are audited. No model-generated identity, arbitrary shell, or direct Issue writer is available.

Local sandbox: `python scripts/sandbox.py snapshot.json` runs the fixed image with read-only input, bounded output, no network, no capabilities, a 64 MiB memory limit and a wall timeout. K8s path: Worker calls the fenced Go `sandbox` operation; Go creates only the fixed Job in `incident-sandbox` with default-deny networking and namespace-scoped RBAC. This threat model covers a predefined analysis script, not arbitrary hostile code.
