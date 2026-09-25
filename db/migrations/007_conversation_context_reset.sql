SET ROLE incident_api;
SET search_path=business;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_after_seq bigint NOT NULL DEFAULT 0;
ALTER TABLE conversation_turns ADD COLUMN IF NOT EXISTS has_query_anchor boolean NOT NULL DEFAULT false;
-- Legacy frozen histories carried a server-generated query-anchor header.
-- Preserve that fact for retries created before the explicit column existed.
UPDATE conversation_turns SET has_query_anchor=true
 WHERE NOT has_query_anchor AND history->0->>'role'='assistant'
 AND history->0->>'content' LIKE '历史查询上下文（%';
INSERT INTO schema_version VALUES(7) ON CONFLICT DO NOTHING;
RESET ROLE;
