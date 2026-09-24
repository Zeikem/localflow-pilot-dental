# LocalFlow Core

Backend multiempresa para captar conversaciones de WhatsApp, calificarlas, agendar citas sin dobles reservas, sincronizar con calendario externo, ejecutar handoff humano y automatizar recordatorios/reseñas.

## Alcance actual

- FastAPI + SQLAlchemy + PostgreSQL/SQLite para desarrollo.
- Flujo conversacional multiempresa y multi-vertical.
- Agenda interna transaccional con holds, idempotencia, cancelación y reprogramación segura.
- Google Calendar por tenant con credenciales configurables y sincronización asíncrona.
- Outbox para WhatsApp con reintentos y plantillas.
- Workers separados para outbox y sincronización de calendario.
- Configuraciones demo para dental, óptica y fisioterapia.
- Configuración de Railway y documentación de despliegue.

## Seguridad

No subas credenciales reales al repositorio. Usa variables de entorno o secretos del proveedor de despliegue. Los archivos `.env.example` y `.env.production.example` contienen solamente valores de ejemplo.

## Desarrollo local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
pytest
uvicorn app.main:app --reload
```

## Procesos

API:

```bash
./bin/start-api
```

Worker de WhatsApp/outbox:

```bash
./bin/start-outbox
```

Worker de Calendar:

```bash
./bin/start-calendar
```

## Despliegue

Consulta `docs/RAILWAY_DEPLOY.md` y `docs/DEPLOYMENT_CHECKLIST.md`. La configuración de producción debe cargar secretos fuera del repositorio.

## Piloto dental

La plantilla base está en `tenant_configs/dental.pilot.example.json`. El flujo objetivo es Google/WhatsApp → calificación → disponibilidad → cita → recordatorio → cancelación/reprogramación → reseña.
