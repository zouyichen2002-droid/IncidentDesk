# Lifecycle and operational boundaries

Evidence inherits task/team scope. Export and replay recheck current membership. Source invalidation changes the service watermark, invalidates unexecuted approvals and expires confirmed memories. Content deletion clears business report/manifest and event payloads; checkpoint/cache/object access must additionally match current watermark. Agent cache keys include subject, team, service, exact time range, ontology/mapping version and watermark. Source index stores versions/tombstones and unavailable markers.

Default retention: snapshots/cache 30 days, staged object cleanup after one hour, business audit metadata retained until an explicit administrative retention run. `Artifacts.cleanup(days)` deletes staged/expired objects and metadata. Backups are separate retained artifacts; restore is an administrative workflow, never an alternate replay endpoint. The demo seed and fixtures contain no real business secrets.

Run `python scripts/backup_restore.py` in the uv environment for a snapshot and independent restore. Report contains measured recovery time and consistency checks. RPO is the dump's consistent snapshot; later writes are excluded. PostgreSQL here is single-instance and is not high availability.

When a task is stuck: inspect queue/lease metrics, task events and Worker readiness; terminated workers are recovered after lease expiry. An `unknown` action must be reconciled by marker; do not reset it to approved. If the issue cannot be uniquely located, an authorized human must inspect the configured test repository.

Retention command: `uv run --project worker python scripts/retention.py --days 30`. Supply CHECKPOINT_DATABASE_URL and S3_ENDPOINT for agent checkpoint/cache and object physical cleanup. Run from the repository root. The test `scripts/retention_check.py` ages only its newly generated disposable fixture and verifies report redaction, checkpoint removal and S3 deletion. Current-scope API fences operate immediately, independently of physical cleanup scheduling. The default setup does not install an automatic deletion schedule.
