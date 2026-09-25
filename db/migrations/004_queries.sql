SET ROLE incident_api;
SET search_path=business;
CREATE TABLE IF NOT EXISTS query_datasets (
 id text PRIMARY KEY, team text NOT NULL, name text NOT NULL, enabled boolean NOT NULL DEFAULT true
);
INSERT INTO query_datasets(id,team,name) VALUES('commerce','orders','电商演示数仓') ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS unified_requests (subject text NOT NULL, idem text NOT NULL, request_hash text NOT NULL, kind text, PRIMARY KEY(subject,idem));
CREATE TABLE IF NOT EXISTS data_queries (
 id uuid PRIMARY KEY, subject text NOT NULL, dataset text NOT NULL REFERENCES query_datasets(id),
 question text NOT NULL, status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','failed')),
 idem text NOT NULL, request_hash text NOT NULL, result jsonb, progress jsonb NOT NULL DEFAULT '[]', error text,
 attempts integer NOT NULL DEFAULT 0, lease_until timestamptz, fence uuid,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(subject,idem)
);
CREATE INDEX IF NOT EXISTS data_queries_pending ON data_queries(status,created_at);
INSERT INTO schema_version VALUES(4) ON CONFLICT DO NOTHING;
RESET ROLE;
