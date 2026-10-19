"""Read-only administrative bridge for LocalFlow Dental.

This endpoint NEVER exposes phone numbers, message texts, raw payloads,
answers, treatment details, Meta credentials or payment details.
The existing admin token provides authentication, and every query is
restricted to one active tenant selected explicitly.
"""
import hashlib
import hmac
import re
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Appointment, InboundEvent, Lead, Tenant

router = APIRouter(prefix="/admin/bridge", tags=["bridge"])


def require_bridge_token(x_localflow_bridge_token: str | None = Header(default=None)) -> None:
    """Dedicated read-only scope; disabled until a distinct secret is configured."""
    expected = get_settings().localflow_bridge_read_token
    if not expected or len(expected) < 32:
        raise HTTPException(status_code=503, detail="Read-only bridge not configured.")
    if not x_localflow_bridge_token or not hmac.compare_digest(
        x_localflow_bridge_token, expected
    ):
        raise HTTPException(status_code=401, detail="Invalid bridge credential.")


_CURSOR_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _tenant(db: Session, slug: str) -> Tenant:
    if not get_settings().localflow_bridge_tenant_slug or slug != get_settings().localflow_bridge_tenant_slug:
        raise HTTPException(status_code=404, detail="Clinic not available for this bridge.")
    tenant = db.scalar(
        select(Tenant).where(Tenant.slug == slug, Tenant.active.is_(True))
    )
    if tenant is None:
        # Avoid tenant enumeration except to holders of admin credentials.
        raise HTTPException(status_code=404, detail="Active clinic not found.")
    return tenant


def _parse_cursor(value: str | None):
    if not value:
        return None
    try:
        dt_s, obj_id = value.rsplit("|", 1)
        dt = datetime.fromisoformat(dt_s)
        if not _CURSOR_RE.fullmatch(obj_id):
            raise ValueError
        return dt, obj_id
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid cursor.") from None


def _status_label(value: str) -> str:
    return {
        "active": "En proceso",
        "human_handoff": "Requiere recepción",
        "awaiting_slot": "Esperando horario",
        "awaiting_confirmation": "Confirmación pendiente",
        "booked": "Cita confirmada",
        "completed": "Finalizado",
        "closed": "Finalizado",
    }.get(value, "En proceso")


@router.get("/events", dependencies=[Depends(require_bridge_token)])
def bridge_events(
    tenant_slug: str = Query(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9_-]*$"),
    cursor: str | None = Query(default=None, max_length=140),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    tenant = _tenant(db, tenant_slug)
    query = (
        select(InboundEvent, Lead.status)
        .outerjoin(Lead, Lead.id == InboundEvent.lead_id)
        .where(InboundEvent.tenant_id == tenant.id)
        .order_by(InboundEvent.created_at, InboundEvent.id)
        .limit(limit + 1)
    )
    last = _parse_cursor(cursor)
    if last:
        when, item_id = last
        query = query.where(or_(
            InboundEvent.created_at > when,
            and_(InboundEvent.created_at == when, InboundEvent.id > item_id),
        ))
    rows = db.execute(query).all()
    page = rows[:limit]
    events = [{
        "event_digest": hashlib.sha256(record.message_id.encode("utf-8")).hexdigest(),
        "received_at": record.created_at.isoformat(),
        "category": _status_label(status or "active"),
        "channel": "WhatsApp",
    } for record, status in page]
    has_more = len(rows) > limit
    next_cursor = (
        f"{page[-1][0].created_at.isoformat()}|{page[-1][0].id}"
        if has_more and page else None
    )
    return {
        "version": 1,
        "tenant_slug": tenant_slug,
        "events": events,
        "next_cursor": next_cursor,
    }


@router.get("/appointments", dependencies=[Depends(require_bridge_token)])
def bridge_appointments(
    tenant_slug: str = Query(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9_-]*$"),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    tenant = _tenant(db, tenant_slug)
    rows = db.scalars(
        select(Appointment)
        .where(Appointment.tenant_id == tenant.id)
        .order_by(Appointment.start_at.desc(), Appointment.id.desc())
        .limit(limit)
    ).all()
    return {
        "version": 1,
        "tenant_slug": tenant_slug,
        "appointments": [{
            "id": row.id,
            "start_at": row.start_at.isoformat(),
            "end_at": row.end_at.isoformat(),
            "status": row.status,
            "resource": row.resource_key[:120],
            "service": row.service_key[:120],
        } for row in rows],
    }
