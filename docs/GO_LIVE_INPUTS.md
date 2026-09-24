# Datos que hacen falta para activar el piloto real

No compartas secretos por texto si puedes conectarlos directamente al servicio.

## WhatsApp / Meta
- `phone_number_id`
- `WHATSAPP_APP_SECRET`
- token de acceso del número
- verify token elegido para el webhook
- aprobación de las plantillas:
  - `recordatorio_cita_localflow`
  - `solicitud_resena_localflow`

## Clínica piloto
- nombre comercial
- servicios y duración real
- horarios reales
- días cerrados
- quién recibe handoffs urgentes
- URL directa para dejar reseña en Google

## Google Calendar
- calendario a usar para el piloto
- permiso para que la integración lea disponibilidad y cree/elimine eventos

Una vez conectados GitHub, Railway y Google Calendar, ChatGPT puede encargarse del despliegue y pruebas disponibles mediante esas conexiones. La configuración de WhatsApp Business/Meta seguirá requiriendo los datos y aprobaciones del propietario de la cuenta.
