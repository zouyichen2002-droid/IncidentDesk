SET ROLE incident_api;
SET search_path=business;
-- Persist the first routing decision/reply so retries retain the same resolved question.
ALTER TABLE unified_requests ADD COLUMN IF NOT EXISTS decision jsonb;
INSERT INTO schema_version VALUES(5) ON CONFLICT DO NOTHING;
RESET ROLE;
