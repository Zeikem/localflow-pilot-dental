import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
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
