SET ROLE incident_api;
SET search_path=business;
ALTER TABLE investigations ADD COLUMN IF NOT EXISTS trace_id text;
CREATE TABLE IF NOT EXISTS rate_limits(subject text,window_start bigint,count int,PRIMARY KEY(subject,window_start));
CREATE TABLE IF NOT EXISTS source_changes(service text REFERENCES services(id),watermark bigint,kind text,created_at timestamptz DEFAULT now(),PRIMARY KEY(service,watermark));
INSERT INTO schema_version VALUES(2) ON CONFLICT DO NOTHING;
RESET ROLE;
