# ADR 0001 — durable ownership and bounded execution

Accepted 2026-09-24. Go owns `business`, PostgreSQL task claims, fencing generations, membership, action/approval state and GitHub credentials. Python owns `agent` checkpoints/context only and accesses business exclusively over versioned HTTP. A separate source role reads `sources`. Every tool revalidates the task lease and original principal with Go. Expired generations get separate checkpoint namespaces; a replacement copies only the previously committed checkpoint into its namespace, never shares a mutable checkpoint with an old process.

Go uses standard net/http and pgx v5. Read committed transactions use locked rows and a transaction advisory lock to serialize global admission/claim counters. External calls never occur inside a DB transaction. Action state is durably `executing` before an external request; interruption leaves an unknown result, reconciled by an immutable marker rather than automatic re-creation. Editing a draft invalidates approval. Scope/watermark changes invalidate evidence and approval.

LangGraph checkpoints persist read-only computation. A framework-free deterministic executor shares the Context and Runtime contracts. Deep Agents is optional configured model execution with state-only workspace; no shell backend and no business write tools. MCP uses the maintained official SDK. Skills are data manifests; Go authorization remains final.

Local Compose uses a development RS256 OIDC issuer, PostgreSQL 17 and S3-compatible storage. k3d uses k3s network-policy enforcement, verified by a denied Pod rather than assumed from YAML. Helm uses namespace-scoped read-only cluster observation. Single PostgreSQL is explicitly not HA.

Documentation inspected before selection:
- https://github.com/jackc/pgx — maintained v5 driver, native pool and transactions.
- https://docs.langchain.com/oss/python/langgraph/persistence — checkpoints are computation persistence, not business exactly-once.
- https://docs.langchain.com/oss/python/deepagents/overview — harness and state-only backend boundary.
- https://github.com/modelcontextprotocol/python-sdk — official SDK; pin supported v1 maintenance line for stable API.
- https://kubernetes.io/docs/concepts/services-networking/network-policies/ — policy requires enforcing network implementation.
- https://k3d.io/stable/usage/commands/k3d_cluster_create/ — local k3s lifecycle.

Exact selected versions live in go.mod/go.sum, uv.lock, package-lock.json and image configuration. Lock resolution and runtime verification determine compatibility, not web claims of latest versions.

Object-store selection correction: official MinIO repository was found archived/unmaintained during verification, and its historical Docker image is unavailable. Use maintained SeaweedFS S3 (`chrislusf/seaweedfs:3.97`) instead; this preserves the PRD's S3 contract. Local endpoint is private and loopback-only. https://github.com/seaweedfs/seaweedfs

Fault-test finding: signalling PID 1 from within its own PID namespace did not suspend the worker in the first SIGSTOP test. The worker now runs as a normal child of a minimal signal-forwarding entrypoint. The takeover script discovers that child through `/proc` and suspends/resumes the actual Python process, while the Go lease clock continues independently. A failed test is retained until the real suspension/recovery run passes.

Memory revocation conservatively advances context freshness for its service. This invalidates dependent draft approvals and hides stale reports, instead of retaining a revoked memory through an old ContextBundle. Cache hits independently refresh reviewed memory under current authorization. This favors correctness over cache hit rate.
