SET ROLE incident_api;
SET search_path=business;
ALTER TABLE query_datasets ADD COLUMN IF NOT EXISTS version text NOT NULL DEFAULT 'teaching-2025q1-v1';
CREATE TABLE IF NOT EXISTS conversations (
 id uuid PRIMARY KEY, subject text NOT NULL, create_idem text NOT NULL,
 title text NOT NULL DEFAULT '新对话', revision bigint NOT NULL DEFAULT 0,
 required_teams text[] NOT NULL DEFAULT '{}', required_datasets text[] NOT NULL DEFAULT '{}',
 summary jsonb NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(subject,create_idem)
);
CREATE INDEX IF NOT EXISTS conversations_owner ON conversations(subject,updated_at DESC,id);
CREATE TABLE IF NOT EXISTS conversation_turns (
 id uuid PRIMARY KEY, conversation uuid NOT NULL REFERENCES conversations(id),
 seq bigserial UNIQUE, idem text NOT NULL, request_hash text NOT NULL, base_revision bigint NOT NULL,
 input jsonb NOT NULL, history jsonb NOT NULL, status text NOT NULL CHECK(status IN ('pending','completed','failed')),
 response jsonb, response_status integer, error text, fence uuid NOT NULL, lease_until timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(conversation,idem)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_conversation_turn ON conversation_turns(conversation) WHERE status='pending';
CREATE INDEX IF NOT EXISTS conversation_turn_order ON conversation_turns(conversation,seq DESC);
INSERT INTO schema_version VALUES(6) ON CONFLICT DO NOTHING;
RESET ROLE;
