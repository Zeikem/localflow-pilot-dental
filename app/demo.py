"""Demostración segura de reservas: usa el backend real y SQLite en memoria.

Ejecutar: python -m app.demo
          python -m app.demo --json

No usa Meta, Google Calendar, tokens de IA ni la base de datos de producción.
Las conversaciones son simuladas y nunca se envían por WhatsApp.
"""

import argparse
import copy
import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Appointment, Lead, OutboxMessage, Tenant
from app.services.conversation import process_inbound_message
from app.services.webhook_parser import InboundWhatsAppMessage


DEMO_PHONE = "PHONE-DEMO-LOCAL-ONLY"
DEMO_WA_ID = "5210000000000"
SAMPLE_CONFIG = (
    Path(__file__).resolve().parent.parent
    / "tenant_configs"
    / "dental.pilot.example.json"
)

# El flujo es el de producción. Sólo los datos y el proveedor de calendario
# cambian: una agenda interna y una cuenta de WhatsApp totalmente ficticias.
SCRIPT = (
    "Hola",
    "Sofía",
    "1",  # Valoración
    "2",  # No es urgente
    "1",  # Primer horario ofrecido
    "CONFIRMAR",
)


def run_demo() -> dict:
    source = json.loads(SAMPLE_CONFIG.read_text(encoding="utf-8"))
    spec = copy.deepcopy(source["workflow_spec"])
    spec["schedule"]["provider"] = "internal"
    spec.pop("direct_booking", None)
    spec.pop("automations", None)

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        Base.metadata.create_all(engine)
        make_session = sessionmaker(bind=engine, expire_on_commit=False)
        with make_session() as db:
            tenant = Tenant(
                slug="demo-localflow-synthetic",
                name="Clínica Dental de Demostración",
                niche="dental",
                timezone="America/Mexico_City",
                whatsapp_phone_number_id=DEMO_PHONE,
                whatsapp_token_env="DEMO_NO_ACCESS_TOKEN",
                workflow_spec=spec,
            )
            db.add(tenant)
            db.commit()

            transcript = []
            for index, incoming in enumerate(SCRIPT, start=1):
                before = {
                    row.id
                    for row in db.scalars(select(OutboxMessage)).all()
                }
                msg = InboundWhatsAppMessage(
                    message_id=f"demo-synthetic-{index}",
                    phone_number_id=DEMO_PHONE,
                    wa_id=DEMO_WA_ID,
                    message_type="text",
                    text=incoming,
                    raw={"demo": True, "synthetic": True},
                )
                processed = process_inbound_message(db, msg)
                replies = [
                    row.body
                    for row in db.scalars(select(OutboxMessage)).all()
                    if row.id not in before
                ]
                if not processed or len(replies) != 1:
                    raise RuntimeError(
                        f"El paso {index} no produjo exactamente una respuesta."
                    )
                transcript.append({
                    "patient": incoming,
                    "localflow": replies[0],
                })

            lead = db.scalar(select(Lead).where(Lead.wa_id == DEMO_WA_ID))
            appointments = list(db.scalars(select(Appointment)).all())
            if not lead or lead.status != "booked":
                raise RuntimeError("No se completó la reserva del ejemplo.")
            if len(appointments) != 1 or appointments[0].status != "confirmed":
                raise RuntimeError("La agenda interna no confirmó una única cita.")

            appointment = appointments[0]
            return {
                "mode": "offline_synthetic_demonstration",
                "external_integrations_tested": False,
                "production_modified": False,
                "meta_messages_sent": 0,
                "openai_api_calls": 0,
                "calendar_provider": "internal",
                "patient_data": "synthetic",
                "transcript": transcript,
                "appointment_status": appointment.status,
                "appointment_start_utc": appointment.start_at.isoformat(),
                "confirmed_appointments": 1,
            }
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Demostración local segura de LocalFlow")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emite un resumen JSON verificable para pruebas y documentación.",
    )
    args = parser.parse_args()
    result = run_demo()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print("LOCALFLOW | DEMOSTRACIÓN LOCAL (DATOS FICTICIOS)")
    print("No se enviaron mensajes ni se usaron APIs externas.\n")
    for message in result["transcript"]:
        print(f"Paciente: {message['patient']}")
        print(f"LocalFlow: {message['localflow']}\n")
    print("Resultado: 1 cita confirmada en una agenda de prueba.")
    print(f"Inicio UTC: {result['appointment_start_utc']}")


if __name__ == "__main__":
    main()
