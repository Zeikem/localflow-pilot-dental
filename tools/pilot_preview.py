"""Demostración 100% aislada del recorrido WhatsApp -> reserva -> puente.

Ejecutar desde la carpeta de LocalFlow Core: python -m tools.pilot_preview
Sin red, mensajes, Meta, Railway, datos reales ni APIs pagadas.
"""
from sqlalchemy import select

from app.models import Appointment, OutboxMessage
from tests.test_signed_pilot_journey import SignedWhatsAppToBridgeTests

STEPS = (
    "Hola, quiero una cita",
    "Paciente de laboratorio",
    "1",
    "1",
    "CONFIRMAR",
)


def main():
    print("=" * 68)
    print("LOCALFLOW DENTAL | DEMO AISLADA Y FICTICIA")
    print("Motor por reglas; no es IA generativa ni una prueba de Meta.")
    print("No envía WhatsApps, no usa APIs ni la base real.")
    print("=" * 68)
    case = SignedWhatsAppToBridgeTests(
        "test_signed_conversation_books_and_exports_only_metadata"
    )
    case.setUp()
    try:
        seen = set()
        for message in STEPS:
            result = case._send(message)
            if result.status_code != 200 or result.json()["processed"] != 1:
                raise RuntimeError("Fallo en el paso de recepción; demo detenida.")
            current = case.db.scalars(select(OutboxMessage)).all()
            replies = [item for item in current if item.id not in seen]
            seen.update(item.id for item in replies)
            print("\nPACIENTE DEMO: " + message)
            for answer in replies:
                print("RESPUESTA PREPARADA (NO ENVIADA): " + answer.body)

        appointment = case.db.scalar(select(Appointment))
        if appointment is None or appointment.status != "confirmed":
            raise RuntimeError("No se encontró una cita confirmada.")

        events = case._events()
        appointments = case._appointments()
        if events.status_code != 200 or appointments.status_code != 200:
            raise RuntimeError("La consulta del puente protegido falló.")

        print("\n" + "-" * 68)
        print("CITA FICTICIA CONFIRMADA exclusivamente en una base temporal.")
        print("EVENTOS ADMINISTRATIVOS LEÍDOS POR EL PUENTE:", len(events.json()["events"]))
        print("CITAS RESUMIDAS LEÍDAS POR EL PUENTE:", len(appointments.json()["appointments"]))
        print("WHATSAPPS REALES ENVIADOS: 0")
        print("-" * 68)
    finally:
        case.tearDown()


if __name__ == "__main__":
    main()
