-- LocalFlow Core v0.3
-- Google Calendar sync + WhatsApp template scheduling.

ALTER TABLE outbox_messages
    ADD COLUMN IF NOT EXISTS appointment_id VARCHAR(36) NULL REFERENCES appointments(id);

ALTER TABLE outbox_messages
    ADD COLUMN IF NOT EXISTS message_kind VARCHAR(20) NOT NULL DEFAULT 'text';

ALTER TABLE outbox_messages
    ADD COLUMN IF NOT EXISTS template_name VARCHAR(160) NULL;

ALTER TABLE outbox_messages
    ADD COLUMN IF NOT EXISTS template_language VARCHAR(20) NULL;

ALTER TABLE outbox_messages
    ADD COLUMN IF NOT EXISTS template_params JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS ix_outbox_messages_appointment_id
    ON outbox_messages(appointment_id);
CREATE INDEX IF NOT EXISTS ix_outbox_messages_message_kind
    ON outbox_messages(message_kind);

CREATE TABLE IF NOT EXISTS calendar_sync_tasks (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id),
    appointment_id VARCHAR(36) NULL REFERENCES appointments(id),
    action VARCHAR(40) NOT NULL,
    payload JSONB NOT NULL,
    idempotency_key VARCHAR(180) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL,
    locked_at TIMESTAMPTZ NULL,
    last_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_calendar_sync_tenant_idempotency
        UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_calendar_sync_tasks_tenant_id
    ON calendar_sync_tasks(tenant_id);
CREATE INDEX IF NOT EXISTS ix_calendar_sync_tasks_appointment_id
    ON calendar_sync_tasks(appointment_id);
CREATE INDEX IF NOT EXISTS ix_calendar_sync_tasks_action
    ON calendar_sync_tasks(action);
CREATE INDEX IF NOT EXISTS ix_calendar_sync_tasks_status
    ON calendar_sync_tasks(status);
CREATE INDEX IF NOT EXISTS ix_calendar_sync_tasks_next_attempt_at
    ON calendar_sync_tasks(next_attempt_at);
