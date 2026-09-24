# Despliegue del piloto en Railway

Arquitectura de producción:
- PostgreSQL administrado por Railway.
- Servicio `localflow-api` desde este mismo repositorio.
- Servicio `localflow-outbox` desde el mismo repositorio.
- Servicio `localflow-calendar` desde el mismo repositorio.

El `Dockerfile` es común. Los comandos de inicio deben configurarse por servicio:

- API: `/app/bin/start-api`
- Outbox: `/app/bin/start-outbox`
- Calendar worker: `/app/bin/start-calendar`

La API necesita dominio público. Los workers no.

## Variables compartidas

Todos los servicios necesitan `DATABASE_URL`.
La API y Outbox necesitan las variables de WhatsApp.
El API/Calendar worker necesitan las variables de Google Calendar si el tenant usa Google.

Usa `.env.production.example` únicamente como lista de variables; no subas secretos al repositorio.

## Orden de go-live

1. Crear PostgreSQL.
2. Crear API y referenciar `DATABASE_URL`.
3. Crear workers con la misma base.
4. Configurar secretos.
5. Levantar API; el script ejecuta migraciones bajo advisory lock.
6. Ejecutar `python -m app.seed` una vez para cargar tenant.
7. Generar dominio HTTPS.
8. Configurar webhook de WhatsApp hacia `/webhooks/whatsapp`.
9. Probar flujo.
10. Habilitar templates solo después de su aprobación.

Railway puede usar el Dockerfile raíz y comandos de inicio distintos por servicio.
