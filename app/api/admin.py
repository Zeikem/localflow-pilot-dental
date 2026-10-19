import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Tenant, OutboxMessage
from app.services.operator import LeadOperationError, reactivate_lead


router = APIRouter(prefix="/admin", tags=["admin"])


class ReactivateLeadRequest(BaseModel):
    reset_flow: bool = False


def require_admin_token(
    x_localflow_admin_token: str | None = Header(default=None),
) -> None:
    expected = get_settings().admin_api_token
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Admin API is disabled until ADMIN_API_TOKEN is configured.",
        )
    if not x_localflow_admin_token or not hmac.compare_digest(
        x_localflow_admin_token,
        expected,
    ):
        raise HTTPException(status_code=401, detail="Invalid admin token")


@router.post(
    "/leads/{lead_id}/reactivate",
    dependencies=[Depends(require_admin_token)],
)
def reactivate(
    lead_id: str,
    request: ReactivateLeadRequest,
    db: Session = Depends(get_db),
):
    try:
        lead = reactivate_lead(
            db,
            lead_id,
            reset_flow=request.reset_flow,
        )
    except LeadOperationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "lead_id": lead.id,
        "status": lead.status,
        "current_step": lead.current_step,
        "reset_flow": request.reset_flow,
    }


PILOT_SLUG = "dental-pilot-leon"


@router.get("/pilot/status", dependencies=[Depends(require_admin_token)])
def pilot_status(db: Session = Depends(get_db)):
    tenant = db.scalar(select(Tenant).where(Tenant.slug == PILOT_SLUG))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Pilot tenant not found")
    pending = db.scalar(select(func.count()).select_from(OutboxMessage).where(
        OutboxMessage.tenant_id == tenant.id,
        OutboxMessage.status.in_(["pending", "sending"]),
    ))
    return {
        "tenant": tenant.slug,
        "active": tenant.active,
        "inbound_mode": (tenant.workflow_spec or {}).get("inbound_mode"),
        "phone_number_id_is_numeric": bool(tenant.whatsapp_phone_number_id and tenant.whatsapp_phone_number_id.isdecimal()),
        "pending_outbound": pending,
        "workflow_configured": bool((tenant.workflow_spec or {}).get("steps")),
    }


class PilotActivationRequest(BaseModel):
    phone_number_id: str
    confirmed_test_only: bool = False


@router.post("/pilot/activate", dependencies=[Depends(require_admin_token)])
def activate_pilot(request: PilotActivationRequest, db: Session = Depends(get_db)):
    """Only the named test tenant may transition, never enable global sending."""
    if not request.confirmed_test_only:
        raise HTTPException(status_code=400, detail="Explicit test-only confirmation required")
    if not request.phone_number_id.isdecimal() or not 10 <= len(request.phone_number_id) <= 24:
        raise HTTPException(status_code=400, detail="Valid numeric Meta Phone Number ID required")
    tenant = db.scalar(select(Tenant).where(Tenant.slug == PILOT_SLUG).with_for_update())
    if tenant is None:
        raise HTTPException(status_code=404, detail="Pilot tenant not found")
    if not tenant.active:
        raise HTTPException(status_code=409, detail="Inactive tenant")
    spec = dict(tenant.workflow_spec or {})
    if not spec.get("steps"):
        raise HTTPException(status_code=409, detail="Conversational workflow not configured")
    old_phone_id = tenant.whatsapp_phone_number_id
    if old_phone_id.isdecimal() and old_phone_id != request.phone_number_id:
        raise HTTPException(status_code=409, detail="Existing Meta phone binding differs")
    conflicting = db.scalar(select(Tenant.id).where(
        Tenant.whatsapp_phone_number_id == request.phone_number_id,
        Tenant.id != tenant.id,
    ))
    if conflicting:
        raise HTTPException(status_code=409, detail="Meta phone already bound to another tenant")
    pending = db.scalar(select(func.count()).select_from(OutboxMessage).where(
        OutboxMessage.tenant_id == tenant.id,
        OutboxMessage.status.in_(["pending", "sending"]),
    ))
    if pending:
        raise HTTPException(status_code=409, detail="Existing outbound queue requires review")
    spec["inbound_mode"] = "conversation"
    tenant.workflow_spec = spec
    tenant.whatsapp_phone_number_id = request.phone_number_id
    db.commit()
    return {"tenant": PILOT_SLUG, "inbound_mode": "conversation", "phone_binding_confirmed": True}
