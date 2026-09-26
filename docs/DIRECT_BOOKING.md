# Reserva directa del piloto

El backend admite peticiones afirmativas como «quiero una cita mañana a las 4 pm».
La interpretación es determinista y gratuita; no requiere un proveedor LLM.

En workflow_spec del tenant, activar explícitamente:

```json
"direct_booking": {
  "enabled": true,
  "default_service_key": "valoracion",
  "required_fields": []
}
```

El servicio predeterminado debe acordarse con el negocio. La opción vacía de
required_fields es para la demostración del piloto: permite reservar sin pedir
nombre u otros campos. Si se requiere calificación previa, incluir allí sus
claves, por ejemplo ["nombre", "urgencia"]. Las reglas de derivación a humano
se evalúan antes de reservar. No activar la opción en otros clientes sin revisar
sus requisitos de calificación.

La reserva usa la duración del servicio, zona horaria del tenant, horario laboral,
antelación mínima y ventana de reservas. Sólo reserva la hora exacta solicitada;
si está ocupada no elige otra en nombre del cliente. Una hora ambigua requiere
am/pm. Una cita ya confirmada conserva el flujo de CANCELAR y REPROGRAMAR.

Para Google Calendar, configurar en api-image y calendar-worker:
- DENTAL_PILOT_GOOGLE_SERVICE_ACCOUNT_JSON
- DENTAL_PILOT_GOOGLE_CALENDAR_ID

Esos nombres deben coincidir con schedule.google.credentials_env y
schedule.resources[].calendar_id_env del tenant real. Compartir el calendario
con la identidad de esas credenciales. No pegar secretos en el chat.
El tenant real vive en PostgreSQL: editar una plantilla JSON del repositorio no
lo actualiza. No ejecutar app.seed sobre producción, porque sobrescribe tenants.

Prueba de aceptación: enviar un mensaje con fecha y hora de apertura; comprobar
una sola cita confirmada, external_event_id y respuesta en WhatsApp. Repetir el
mismo message_id no debe crear otro evento. Simular disponibilidad ocupada y error
de Google: ninguna respuesta debe afirmar que la cita quedó confirmada.

Las pruebas automatizadas usan SQLite y un proveedor simulado. No sustituyen la
prueba real con PostgreSQL, Meta y Google Calendar autorizados.
