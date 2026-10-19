"""Optional human-reviewed administrative drafting. No patient data or sending."""
from __future__ import annotations
import re
from dataclasses import dataclass
import httpx
from app.config import get_settings

INTENTS = frozenset({
    "saludo", "horarios", "servicios", "precios", "agendar",
    "reprogramar", "cancelar", "urgencia", "otro",
})
# Only a short public clinic fact is allowed. Never pass patient conversation
# text, patient names, phone numbers, email addresses or medical histories.
_PII_OR_PROMPT = re.compile(
    r"(?:\b\d[\d\s+().-]{8,}\d\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"https?://|[{}<>]|\b(?:ignora|ignore|system|developer|prompt|paciente|"
    r"diagn[oó]stico|s[ií]ntoma|medicaci[oó]n|historial)\b)",
    re.IGNORECASE,
)
_UNSAFE_DRAFT = re.compile(
    r"\b(?:diagn[oó]stico|receta|garantizado|curaci[oó]n|tratamiento recomendado|"
    r"cita (?:confirmada|reservada)|ya (?:agend[eé]|reserv[eé])|"
    r"urgencia resuelta)\b",
    re.IGNORECASE,
)

@dataclass(frozen=True)
class CopilotDraft:
    draft: str
    source: str
    requires_human_review: bool = True
    sent: bool = False
    appointment_created: bool = False
    api_called: bool = False

class InvalidVerifiedFact(ValueError):
    pass

def _fact(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidVerifiedFact("El dato verificado debe ser texto.")
    item = " ".join(value.split())
    if len(item) > 160 or _PII_OR_PROMPT.search(item):
        raise InvalidVerifiedFact(
            "Solo se admite información pública breve, sin datos de pacientes."
        )
    return item

def _template(intent: str, fact: str) -> str:
    if intent == "saludo":
        return "Hola. Gracias por escribirnos. ¿En qué podemos orientarte?"
    if intent == "urgencia":
        return (
            "Tu solicitud necesita atención de una persona. "
            "Si hay una emergencia, busca atención médica presencial inmediata."
        )
    if intent == "agendar":
        return "Con gusto. Recepción revisará disponibilidad antes de confirmar tu cita."
    if intent == "reprogramar":
        return "Recepción revisará tu solicitud de cambio y confirmará las opciones disponibles."
    if intent == "cancelar":
        return "Recepción revisará la solicitud de cancelación antes de confirmarla."
    if intent in {"horarios", "servicios", "precios"} and fact:
        prefix = {
            "horarios": "Nuestros horarios confirmados son: ",
            "servicios": "Estos servicios están confirmados: ",
            "precios": "Información de precios confirmada: ",
        }[intent]
        return prefix + fact + ". Recepción puede ayudarte con más detalles."
    return "Una persona de recepción revisará tu consulta y te orientará."

def _extract_text(obj: dict) -> str:
    if obj.get("status") != "completed":
        return ""
    for item in obj.get("output", []):
        if item.get("type") == "message" and item.get("role") == "assistant":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    return str(part.get("text", "")).strip()
    return ""

def draft_administrative_reply(
    intent: str, *, verified_public_fact: str = "", request_ai: bool = False,
) -> CopilotDraft:
    """No Meta calls or database writes; optional OpenAI requests are off by default."""
    if intent not in INTENTS:
        raise ValueError("Tipo de consulta desconocido.")
    fact = _fact(verified_public_fact)
    base = _template(intent, fact)
    fallback = CopilotDraft(draft=base, source="plantilla")
    # Safety-critical actions always stay deterministic and human reviewed.
    if intent in {"urgencia", "cancelar", "reprogramar", "agendar", "otro"}:
        return fallback
    if intent in {"horarios", "servicios", "precios"} and not fact:
        return fallback
    cfg = get_settings()
    if not (request_ai and cfg.localflow_ai_enabled and cfg.localflow_ai_api_key
            and cfg.localflow_ai_model):
        return fallback
    try:
        with httpx.Client(timeout=8.0, follow_redirects=False) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {cfg.localflow_ai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": cfg.localflow_ai_model,
                    "store": False,
                    "max_output_tokens": 160,
                    "instructions": (
                        "Eres asistente para redactar borradores administrativos de una "
                        "clínica dental de México. Reformula el texto proporcionado "
                        "sin añadir datos, disponibilidad, precios o garantías. "
                        "No des consejos médicos ni afirmes que hay una cita confirmada. "
                        "La respuesta es para revisión humana, nunca para envío directo. "
                        "Solo devuelve una frase breve en español."
                    ),
                    "input": (
                        f"Categoría: {intent}. Dato público verificado: {fact}. "
                        f"Borrador a reformular: {base}"
                    ),
                },
            )
            response.raise_for_status()
            suggestion = _extract_text(response.json())
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return fallback
    if not (10 <= len(suggestion) <= 360):
        return fallback
    if _UNSAFE_DRAFT.search(suggestion) or _PII_OR_PROMPT.search(suggestion):
        return fallback
    return CopilotDraft(
        draft=suggestion, source="ia_sugerencia", requires_human_review=True,
        api_called=True,
    )
