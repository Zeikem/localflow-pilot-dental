"""Read-only, credential-safe configuration checks for the LocalFlow pilot.

A passing report means required values are present, NOT that Meta, Google, or
background workers have been successfully tested.
"""
import os

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Tenant


def check_readiness(db: Session, tenant_slug: str) -> dict:
    """Inspect only this API process and database without disclosing secrets."""
    db.execute(text("SELECT 1")).scalar_one()
    tenant = db.scalar(
        select(Tenant).where(Tenant.slug == tenant_slug, Tenant.active.is_(True))
    )
    settings = get_settings()
    checks = {
        "database_reachable": True,
        "tenant_active": tenant is not None,
        "whatsapp_app_secret_present": bool(settings.whatsapp_app_secret.strip()),
        "whatsapp_verify_token_configured": (
            bool(settings.whatsapp_verify_token.strip())
            and settings.whatsapp_verify_token != "dev-verify-token"
        ),
        "whatsapp_access_token_present": False,
        "schedule_configured": False,
        "calendar_credentials_present": False,
        "calendar_ids_present": False,
    }
    provider = None
    if tenant:
        checks["whatsapp_access_token_present"] = bool(
            os.getenv(tenant.whatsapp_token_env or "", "").strip()
        )
        schedule = (tenant.workflow_spec or {}).get("schedule") or {}
        provider = str(schedule.get("provider", "internal")).strip().casefold()
        resources = schedule.get("resources") or []
        services = schedule.get("services") or []
        checks["schedule_configured"] = (
            provider in {"internal", "google_calendar"}
            and isinstance(resources, list)
            and bool(resources)
            and isinstance(services, list)
            and bool(services)
        )
        if provider == "internal":
            checks["calendar_credentials_present"] = True  # not required
            checks["calendar_ids_present"] = True  # not required
        elif provider == "google_calendar":
            google = schedule.get("google") or {}
            credentials_env = str(google.get("credentials_env", "")).strip()
            checks["calendar_credentials_present"] = bool(
                credentials_env and os.getenv(credentials_env, "").strip()
            )
            checks["calendar_ids_present"] = all(
                isinstance(resource, dict)
                and (env_name := str(resource.get("calendar_id_env", "")).strip())
                and os.getenv(env_name, "").strip()
                for resource in resources
            ) and bool(resources)

    return {
        "status": "configuration_complete" if all(checks.values()) else "incomplete",
        "scope": "api_instance_configuration_only",
        "provider": provider,
        "checks": checks,
        "external_integrations_verified": False,
        "worker_configuration_verified": False,
    }
