"""Independent staff credential; draft-only endpoint with no outgoing messages."""
import hmac
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from app.config import get_settings
from app.services.ai_copilot import InvalidVerifiedFact, draft_administrative_reply

router = APIRouter(prefix="/admin/copilot", tags=["copilot"])

def require_copilot_token(
    x_localflow_copilot_token: str | None = Header(default=None),
) -> None:
    expected = get_settings().localflow_copilot_token
    if not expected or len(expected) < 32:
        raise HTTPException(status_code=503, detail="El copiloto no está habilitado.")
    if not x_localflow_copilot_token or not hmac.compare_digest(
        x_localflow_copilot_token, expected
    ):
        raise HTTPException(status_code=401, detail="Credencial inválida.")

class DraftRequest(BaseModel):
    intent: Literal[
        "saludo", "horarios", "servicios", "precios", "agendar",
        "reprogramar", "cancelar", "urgencia", "otro",
    ]
    verified_public_fact: str = Field(default="", max_length=160)
    request_ai: bool = False

@router.post("/draft", dependencies=[Depends(require_copilot_token)])
def draft(req: DraftRequest):
    try:
        result = draft_administrative_reply(
            req.intent, verified_public_fact=req.verified_public_fact,
            request_ai=req.request_ai,
        )
    except (ValueError, InvalidVerifiedFact) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {
        "draft": result.draft,
        "source": result.source,
        "requires_human_review": result.requires_human_review,
        "sent": False,
        "appointment_created": False,
        "api_called": result.api_called,
    }
