# LocalFlow Core v0.3

Motor multiempresa para **captación, atención digital y agendamiento automatizado** de negocios locales.

Flujo base:

**Google Maps / enlace / anuncio → WhatsApp → calificación → agenda → confirmación → recordatorio → reseña / handoff humano**

Diseñado para que 80–90% del código sea común y la personalización por cliente viva en configuración.

## Qué incluye

- FastAPI + PostgreSQL + SQLAlchemy.
- Webhook de WhatsApp Cloud API con validación HMAC.
- Deduplicación/idempotencia de mensajes entrantes.
- Multi-tenant por `tenant_id`.
- Workflow declarativo por JSON.
- Dental, óptica y fisioterapia sobre el mismo motor.
- Agenda interna con disponibilidad, duración por servicio y recursos.
- Apartado temporal con expiración.
- Protección contra doble reserva.
- Confirmación, cancelación y reprogramación segura.
- Google Calendar opcional como proveedor externo.
- Revisión de `freebusy` antes de confirmar.
- Recuperación idempotente de eventos de Google.
- Cola de compensación/reintento para eliminaciones de Google Calendar.
- Outbox transaccional para WhatsApp.
- Mensajes programados mediante plantillas de WhatsApp.
- Recordatorio pre-cita configurable.
- Solicitud de reseña post-cita configurable.
- Cancelación automática de recordatorios al cancelar/reprogramar.
- Handoff humano.
- Reactivación controlada mediante endpoint administrativo.
- Reglas de urgencia configurables.
- Migraciones SQL de v0.1→v0.2→v0.3.
- Docker Compose con API, PostgreSQL, worker de WhatsApp y worker de Calendar Sync.
- 38 pruebas automatizadas.

## Límites deliberados

LocalFlow no contiene credenciales reales ni plantillas aprobadas por Meta. Para activar un cliente real debes configurar:
- WhatsApp Cloud API;
- tokens/secretos;
- dominio HTTPS/webhook;
- plantillas aprobadas si se usarán recordatorios o reseñas programadas;
- Google Calendar si el tenant usa `provider=google_calendar`.

No se intenta diagnosticar condiciones clínicas. Las solicitudes urgentes del flujo dental se escalan a una persona.

## Arranque local

```bash
cp .env.example .env
docker compose up --build -d db api worker calendar-worker
docker compose exec api python -m app.seed
curl http://localhost:8000/health
```

Pruebas:

```bash
python -m unittest discover -s tests -v
```

## Configuración de clientes

Usa `tenant_configs/` como plantilla.

Ejemplos:
- `dental.demo.json`
- `optica.demo.json`
- `fisioterapia.demo.json`
- `dental.google_calendar.example.json`

La configuración controla:
- textos;
- servicios;
- duración;
- horarios;
- recursos;
- reglas de urgencia/handoff;
- proveedor de calendario;
- URL de reseña;
- plantillas de recordatorio/reseña.

## Google Calendar

Para un tenant con Google:

```json
"schedule": {
  "provider": "google_calendar",
  "google": {
    "credentials_env": "DENTAL_GOOGLE_SERVICE_ACCOUNT_JSON",
    "delegated_subject_env": "DENTAL_GOOGLE_DELEGATED_SUBJECT"
  },
  "resources": [
    {
      "key": "recurso-1",
      "calendar_id_env": "DENTAL_GOOGLE_CALENDAR_ID"
    }
  ]
}
```

El calendario debe ser accesible por la identidad usada por las credenciales.

## WhatsApp programado

Los recordatorios y solicitudes de reseña se crean como mensajes `template`, no como texto libre. Mantén las automatizaciones deshabilitadas hasta que las plantillas hayan sido aprobadas y probadas.

## Handoff / reactivación

Cuando el lead pasa a `human_handoff`, el bot deja de contestar para no competir con recepción.

Para reactivarlo:

```http
POST /admin/leads/{lead_id}/reactivate
X-LocalFlow-Admin-Token: <ADMIN_API_TOKEN>
Content-Type: application/json

{"reset_flow": false}
```

## Migraciones

Para una base existente:
1. `migrations/001_v0_2_appointments.sql`
2. `migrations/002_v0_3_calendar_and_templates.sql`

`create_all()` sirve para una base nueva; no sustituye las migraciones de una base ya existente.

## Documentación incluida

- `docs/BUSINESS_PLAYBOOK.md`
- `docs/ONBOARDING_CLIENT.md`
- `docs/META_TEMPLATES.md`
- `docs/DEPLOYMENT_CHECKLIST.md`
- `TEST_RESULTS.md`

## Estructura

```text
app/
  api/
  core/
  domain/
  services/
  workers/
tenant_configs/
migrations/
docs/
tests/
```
