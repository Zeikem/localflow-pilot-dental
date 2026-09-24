from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class GoogleCalendarConfigError(ValueError):
    pass


class GoogleCalendarAPIError(RuntimeError):
    pass


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class BusyInterval:
    start: datetime
    end: datetime

    def overlaps(self, start: datetime, end: datetime) -> bool:
        start = _utc(start)
        end = _utc(end)
        return self.start < end and start < self.end


class GoogleCalendarGateway:
    """Thin Google Calendar API wrapper.

    Credentials are loaded lazily so LocalFlow can still run with the internal
    provider without Google libraries or credentials being used at runtime.
    """

    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def __init__(
        self,
        *,
        credentials_env: str,
        delegated_subject_env: str | None = None,
    ) -> None:
        self.credentials_env = credentials_env
        self.delegated_subject_env = delegated_subject_env
        self._service = None

    def _build_service(self):
        raw = os.getenv(self.credentials_env, "").strip()
        if not raw:
            raise GoogleCalendarConfigError(
                f"Falta la variable de entorno {self.credentials_env} con el JSON "
                "de la cuenta de servicio de Google."
            )

        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GoogleCalendarConfigError(
                f"{self.credentials_env} no contiene JSON válido."
            ) from exc

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GoogleCalendarConfigError(
                "Faltan dependencias de Google Calendar. Instala el proyecto v0.3 completo."
            ) from exc

        try:
            credentials = service_account.Credentials.from_service_account_info(
                info,
                scopes=self.SCOPES,
            )
            if self.delegated_subject_env:
                subject = os.getenv(self.delegated_subject_env, "").strip()
                if subject:
                    credentials = credentials.with_subject(subject)

            return build(
                "calendar",
                "v3",
                credentials=credentials,
                cache_discovery=False,
            )
        except Exception as exc:
            raise GoogleCalendarConfigError(
                "No se pudieron inicializar las credenciales de Google Calendar."
            ) from exc

    @property
    def service(self):
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def busy(
        self,
        *,
        calendar_ids: list[str],
        start: datetime,
        end: datetime,
    ) -> dict[str, list[BusyInterval]]:
        if not calendar_ids:
            return {}

        start = _utc(start)
        end = _utc(end)
        body = {
            "timeMin": start.isoformat().replace("+00:00", "Z"),
            "timeMax": end.isoformat().replace("+00:00", "Z"),
            "items": [{"id": calendar_id} for calendar_id in calendar_ids],
        }

        try:
            response = self.service.freebusy().query(body=body).execute()
        except Exception as exc:
            raise GoogleCalendarAPIError(
                "Google Calendar no respondió al consultar disponibilidad."
            ) from exc

        calendars = response.get("calendars", {})
        result: dict[str, list[BusyInterval]] = {}
        for calendar_id in calendar_ids:
            data = calendars.get(calendar_id, {})
            if data.get("errors"):
                raise GoogleCalendarAPIError(
                    f"Google Calendar devolvió un error para {calendar_id}."
                )

            intervals: list[BusyInterval] = []
            for item in data.get("busy", []):
                try:
                    interval = BusyInterval(
                        start=_utc(datetime.fromisoformat(item["start"].replace("Z", "+00:00"))),
                        end=_utc(datetime.fromisoformat(item["end"].replace("Z", "+00:00"))),
                    )
                except Exception as exc:
                    raise GoogleCalendarAPIError(
                        "Google Calendar devolvió un intervalo de disponibilidad inválido."
                    ) from exc
                intervals.append(interval)
            result[calendar_id] = intervals

        return result


    def find_event_id_by_idempotency(
        self,
        *,
        calendar_id: str,
        idempotency_key: str,
        start: datetime,
        end: datetime,
    ) -> str | None:
        """Recover a prior create after a timeout/retry without duplicating the event."""
        try:
            response = self.service.events().list(
                calendarId=calendar_id,
                timeMin=_utc(start).isoformat().replace("+00:00", "Z"),
                timeMax=_utc(end).isoformat().replace("+00:00", "Z"),
                privateExtendedProperty=(
                    f"localflow_idempotency_key={idempotency_key}"
                ),
                singleEvents=True,
                maxResults=2,
            ).execute()
        except Exception as exc:
            raise GoogleCalendarAPIError(
                "No se pudo comprobar la idempotencia en Google Calendar."
            ) from exc

        items = response.get("items", [])
        if not items:
            return None

        event_id = str(items[0].get("id", "")).strip()
        return event_id or None

    def create_event(
        self,
        *,
        calendar_id: str,
        summary: str,
        description: str,
        start: datetime,
        end: datetime,
        timezone_name: str,
        idempotency_key: str,
    ) -> str:
        event = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": _utc(start).isoformat().replace("+00:00", "Z"),
                "timeZone": timezone_name,
            },
            "end": {
                "dateTime": _utc(end).isoformat().replace("+00:00", "Z"),
                "timeZone": timezone_name,
            },
            "extendedProperties": {
                "private": {
                    "localflow_idempotency_key": idempotency_key,
                }
            },
        }

        try:
            created = self.service.events().insert(
                calendarId=calendar_id,
                body=event,
            ).execute()
        except Exception as exc:
            raise GoogleCalendarAPIError(
                "No se pudo crear la cita en Google Calendar."
            ) from exc

        event_id = str(created.get("id", "")).strip()
        if not event_id:
            raise GoogleCalendarAPIError(
                "Google Calendar creó una respuesta sin event id."
            )
        return event_id

    def delete_event(self, *, calendar_id: str, event_id: str) -> None:
        try:
            self.service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
            ).execute()
        except Exception as exc:
            # 404 means the desired end state is already achieved.
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status == 404:
                return
            raise GoogleCalendarAPIError(
                "No se pudo eliminar la cita de Google Calendar."
            ) from exc
