-- LocalFlow Core v0.2
-- Agenda interna multi-tenant.
-- Ejecutar sobre PostgreSQL existente de v0.1 antes de desplegar v0.2.
-- La migración solo agrega tablas nuevas; no modifica columnas existentes.

CREATE TABLE IF NOT EXISTS appointments (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id),
    lead_id VARCHAR(36) NULL REFERENCES leads(id),
    service_key VARCHAR(120) NOT NULL,
    resource_key VARCHAR(120) NOT NULL,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'held',
    hold_expires_at TIMESTAMPTZ NULL,
    idempotency_key VARCHAR(180) NOT NULL,
    supersedes_appointment_id VARCHAR(36) NULL REFERENCES appointments(id),
    external_provider VARCHAR(40) NULL,
    external_event_id VARCHAR(200) NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_appointment_tenant_idempotency
        UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_appointments_tenant_id ON appointments(tenant_id);
CREATE INDEX IF NOT EXISTS ix_appointments_lead_id ON appointments(lead_id);
CREATE INDEX IF NOT EXISTS ix_appointments_service_key ON appointments(service_key);
CREATE INDEX IF NOT EXISTS ix_appointments_resource_key ON appointments(resource_key);
CREATE INDEX IF NOT EXISTS ix_appointments_start_at ON appointments(start_at);
CREATE INDEX IF NOT EXISTS ix_appointments_end_at ON appointments(end_at);
CREATE INDEX IF NOT EXISTS ix_appointments_status ON appointments(status);
CREATE INDEX IF NOT EXISTS ix_appointments_hold_expires_at ON appointments(hold_expires_at);
CREATE INDEX IF NOT EXISTS ix_appointments_supersedes_appointment_id
    ON appointments(supersedes_appointment_id);

CREATE TABLE IF NOT EXISTS appointment_slots (
    id VARCHAR(36) PRIMARY KEY,
    appointment_id VARCHAR(36) NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id),
    resource_key VARCHAR(120) NOT NULL,
    slot_start TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_appointment_slot_resource_start
        UNIQUE (tenant_id, resource_key, slot_start)
);

CREATE INDEX IF NOT EXISTS ix_appointment_slots_appointment_id
    ON appointment_slots(appointment_id);
CREATE INDEX IF NOT EXISTS ix_appointment_slots_tenant_id
    ON appointment_slots(tenant_id);
CREATE INDEX IF NOT EXISTS ix_appointment_slots_resource_key
    ON appointment_slots(resource_key);
CREATE INDEX IF NOT EXISTS ix_appointment_slots_slot_start
    ON appointment_slots(slot_start);
