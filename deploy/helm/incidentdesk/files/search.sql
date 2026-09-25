SET ROLE incident_api;
SET search_path=business;
ALTER TABLE investigations ADD COLUMN IF NOT EXISTS query jsonb NOT NULL DEFAULT '{}';
INSERT INTO schema_version VALUES(3) ON CONFLICT DO NOTHING;
RESET ROLE;
