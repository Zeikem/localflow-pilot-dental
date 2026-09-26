from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import Tenant


@dataclass(frozen=True)
class IntakeHints:
    answers: dict[str, str]
    requested_start: datetime | None = None


_WEEKDAYS = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}

_URGENT_PHRASES = (
    "urgente",
    "emergencia",
    "mucho dolor",
    "dolor fuerte",
    "sangrado",
    "hinchazon",
    "se me cayo un diente",
)

_NON_URGENT_PHRASES = (
    "no es urgente",
    "no urgente",
    "no me urge",
    "puedo agendar",
    "puede esperar",
)


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _service_answer(tenant: Tenant, text: str) -> str | None:
    normalized = _plain(text)
    schedule = (tenant.workflow_spec or {}).get("schedule", {})

    best: tuple[int, str] | None = None
    for service in schedule.get("services", []):
        key = str(service.get("key", "")).strip()
        label = str(service.get("label", key)).strip()
        aliases = [label, key, *[str(x) for x in service.get("aliases", [])]]

        for alias in aliases:
            candidate = _plain(alias).strip()
            if not candidate:
                continue
            if re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", normalized):
                score = len(candidate)
                if best is None or score > best[0]:
                    best = (score, label)
    return best[1] if best else None


def _urgency_answer(tenant: Tenant, text: str) -> str | None:
    normalized = _plain(text)

    if any(phrase in normalized for phrase in _NON_URGENT_PHRASES):
        desired = "no"
    elif any(phrase in normalized for phrase in _URGENT_PHRASES):
        desired = "si"
    else:
        return None

    for step in (tenant.workflow_spec or {}).get("steps", []):
        if str(step.get("key", "")).strip() != "urgencia":
            continue
        for choice in step.get("choices", []):
            normalized_choice = _plain(str(choice))
            if desired == "si" and normalized_choice.startswith("si"):
                return str(choice)
            if desired == "no" and normalized_choice.startswith("no"):
                return str(choice)
    return None


def _parse_time(text: str) -> tuple[int, int] | None:
    normalized = _plain(text)

    patterns = [
        r"\b(?:a\s+las\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        r"\b(?:a\s+las\s+)?(\d{1,2})(?::(\d{2}))?\s+de\s+la\s+(manana|tarde|noche)\b",
        r"\b(?:a\s+las\s+)?(\d{1,2}):(\d{2})\b",
        r"\ba\s+las\s+(\d{1,2})\b",
    ]

    for index, pattern in enumerate(patterns):
        match = re.search(pattern, normalized)
        if not match:
            continue

        hour = int(match.group(1))
        minute = int((match.group(2) if len(match.groups()) >= 2 else None) or 0)
        if minute > 59:
            return None

        marker = match.group(3) if len(match.groups()) >= 3 else None
        if index == 0 and marker:
            if not 1 <= hour <= 12:
                return None
            if marker == "pm" and hour != 12:
                hour += 12
            if marker == "am" and hour == 12:
                hour = 0
        elif index == 1 and marker:
            if not 1 <= hour <= 12:
                return None
            if marker in {"tarde", "noche"} and hour != 12:
                hour += 12
            if marker == "manana" and hour == 12:
                hour = 0
        elif not 0 <= hour <= 23:
            return None

        if index == 3 and 1 <= hour <= 12:
            return None  # Ask AM/PM instead of choosing a different appointment.
        return hour, minute

    return None


def _parse_date(text: str, local_now: datetime) -> datetime | None:
    normalized = _plain(text)

    if re.search(r"\bhoy\b", normalized):
        return local_now
    if re.search(r"(?<!de la )\bmanana\b", normalized):
        return local_now + timedelta(days=1)

    for name, weekday in _WEEKDAYS.items():
        if not re.search(rf"\b{name}\b", normalized):
            continue
        delta = (weekday - local_now.weekday()) % 7
        if delta == 0:
            delta = 7
        return local_now + timedelta(days=delta)

    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", normalized)
    if not match:
        return None

    day = int(match.group(1))
    month = int(match.group(2))
    raw_year = match.group(3)
    year = local_now.year
    if raw_year:
        year = int(raw_year)
        if year < 100:
            year += 2000

    try:
        candidate = local_now.replace(year=year, month=month, day=day)
    except ValueError:
        return None

    if not raw_year and candidate.date() < local_now.date():
        try:
            candidate = candidate.replace(year=year + 1)
        except ValueError:
            return None
    return candidate


def _requested_start(
    tenant: Tenant,
    text: str,
    *,
    now: datetime | None = None,
) -> datetime | None:
    tz = ZoneInfo(tenant.timezone)
    local_now = (now or datetime.now(tz)).astimezone(tz)
    requested_date = _parse_date(text, local_now)
    requested_time = _parse_time(text)

    if requested_date is None or requested_time is None:
        return None

    hour, minute = requested_time
    return requested_date.replace(hour=hour, minute=minute, second=0, microsecond=0)


def interpret_intake(
    tenant: Tenant,
    text: str,
    *,
    now: datetime | None = None,
) -> IntakeHints:
    answers: dict[str, str] = {}

    service = _service_answer(tenant, text)
    if service:
        answers["servicio"] = service

    urgency = _urgency_answer(tenant, text)
    if urgency:
        answers["urgencia"] = urgency

    return IntakeHints(
        answers=answers,
        requested_start=_requested_start(tenant, text, now=now),
    )
