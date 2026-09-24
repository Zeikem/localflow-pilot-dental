import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    niche: Mapped[str] = mapped_column(String(80))
    timezone: Mapped[str] = mapped_column(String(80), default="America/Mexico_City")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    whatsapp_phone_number_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    whatsapp_token_env: Mapped[str] = mapped_column(String(160))
    workflow_spec: Mapped[dict] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("tenant_id", "wa_id", name="uq_lead_tenant_wa"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    wa_id: Mapped[str] = mapped_column(String(40), index=True)
    current_step: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    last_user_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    tenant: Mapped["Tenant"] = relationship()


class InboundEvent(Base):
    __tablename__ = "inbound_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id"), nullable=True, index=True)
    wa_id: Mapped[str] = mapped_column(String(40), index=True)
    message_type: Mapped[str] = mapped_column(String(40))
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id"), nullable=True, index=True)
    to_wa_id: Mapped[str] = mapped_column(String(40), index=True)
    appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id"), nullable=True, index=True
    )

    # text = mensaje libre dentro de la conversación activa.
    # template = plantilla aprobada de WhatsApp para recordatorios/seguimientos programados.
    message_kind: Mapped[str] = mapped_column(String(20), default="text", index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    template_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    template_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    template_params: Mapped[list] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tenant: Mapped["Tenant"] = relationship()


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_appointment_tenant_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id"), nullable=True, index=True)

    service_key: Mapped[str] = mapped_column(String(120), index=True)
    resource_key: Mapped[str] = mapped_column(String(120), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # held -> confirmed -> cancelled / expired
    status: Mapped[str] = mapped_column(String(24), default="held", index=True)
    hold_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(180))
    supersedes_appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id"), nullable=True, index=True
    )

    # Preparado para conectar Google Calendar/Calendly/u otro proveedor sin cambiar el flujo.
    external_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    external_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    slots: Mapped[list["AppointmentSlot"]] = relationship(
        back_populates="appointment",
        cascade="all, delete-orphan",
    )


class AppointmentSlot(Base):
    """Bloqueo atómico de agenda.

    La restricción UNIQUE evita que dos reservas ocupen el mismo bloque de un recurso,
    incluso si dos peticiones llegan prácticamente al mismo tiempo.
    """

    __tablename__ = "appointment_slots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "resource_key",
            "slot_start",
            name="uq_appointment_slot_resource_start",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    appointment_id: Mapped[str] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"),
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    resource_key: Mapped[str] = mapped_column(String(120), index=True)
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    appointment: Mapped["Appointment"] = relationship(back_populates="slots")


class CalendarSyncTask(Base):
    __tablename__ = "calendar_sync_tasks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_calendar_sync_tenant_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(180))

    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tenant: Mapped["Tenant"] = relationship()
