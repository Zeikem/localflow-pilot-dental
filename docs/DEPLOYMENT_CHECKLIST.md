# Checklist de despliegue

## Infraestructura
- [ ] PostgreSQL persistente.
- [ ] HTTPS frente a FastAPI.
- [ ] backups automáticos.
- [ ] variables de entorno/secret manager.
- [ ] `ADMIN_API_TOKEN` largo y aleatorio.
- [ ] workers de Outbox y Calendar Sync activos.

## WhatsApp
- [ ] número conectado a Cloud API.
- [ ] verify token.
- [ ] app secret.
- [ ] access token por tenant.
- [ ] webhook validado.
- [ ] plantillas aprobadas antes de habilitar recordatorios/reseñas.

## Google Calendar
- [ ] API habilitada.
- [ ] cuenta de servicio o credencial adecuada.
- [ ] calendarios compartidos con la identidad que usará la integración.
- [ ] `calendar_id` separado por recurso.
- [ ] prueba de create/freebusy/delete.

## Tenant
- [ ] servicios y duraciones.
- [ ] horarios.
- [ ] reglas de urgencia/handoff.
- [ ] review URL.
- [ ] zona horaria.
- [ ] prueba de cancelación y reprogramación.

## Go-live
- [ ] suite automatizada en verde.
- [ ] prueba de aceptación manual.
- [ ] monitoreo de errores.
- [ ] responsable humano definido.
