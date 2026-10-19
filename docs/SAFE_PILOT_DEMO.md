# Piloto seguro de WhatsApp | Desarrollo aislado

Este cambio parte de `feature/read-only-dentalflow-bridge-20261019` y **NO ESTÁ DESPLEGADO**. La implementación que sigue corriendo en Railway conserva la versión de código anterior.

## Objetivo concreto
Reproducir el flujo técnico real del sistema sin llamadas a Meta, sin gasto en APIs y sin tocar información de pacientes.

## Dos protecciones nuevas
1. `WHATSAPP_OUTBOUND_ENABLED` (booleano de `app.config.Settings`) vale **false** cuando no se configura. Las funciones `WhatsAppClient.send_text` y `send_template` rechazan todo envío cuando el valor es false, antes de leer una credencial o establecer cualquier conexión.
2. El `outbox-worker` no reclama ni reintenta mensajes pendientes mientras el permiso esté desactivado. El envío requiere una **habilitación explícita por servicio, después de revisar destinatarios, consentimiento, costo y configuración**.

**ADVERTENCIA:** este guard solo protege los procesos que ejecuten esta nueva versión. El trabajador existente en Railway todavía utiliza una versión previa. No activar un número real del piloto ni asumir que el worker publicado tiene ya este bloqueo.

## Prueba integral con datos falsos
```powershell
cd C:\Users\Usuario\Documents\LocalFlow-Core-Bridge-20261019\localflow-pilot-dental-main
..\.venv\Scripts\python.exe -m tools.pilot_preview
..\.venv\Scripts\python.exe -m unittest discover -s tests -q
```
También se creó un lanzador local para Windows:
`C:\Users\Usuario\Documents\DentalFlow\DEMOSTRAR_BOT_LOCALFLOW.cmd`

Este programa usa el **webhook real de FastAPI en un TestClient local**, una firma HMAC-SHA256 sintética, el parser real, el motor de conversación, la agenda interna de pruebas, y los dos endpoints del puente administrativo. Toda la base de datos es SQLite temporal en memoria. Las respuestas se quedan en cola, nunca se entregan.

Comprueba: cinco mensajes entrantes, cinco respuestas preparadas, una cita ficticia confirmada, consulta restringida de cinco metadatos de eventos y una cita, aislamiento por clínica, y deduplicación por message_id.

## Límites honestos
- La demostración opera con el motor **basado en reglas**, no genera respuestas mediante una IA generativa.
- No autentica ni envía mensajes reales a Meta. No crea citas reales.
- No conecta todavía la agenda de DentalFlow con Google Calendar ni confirma disponibilidad del dentista.
- No sincroniza automáticamente con el Railway en producción. El puente real sí está disponible, pero la clínica piloto productiva continúa vacía y deliberadamente sin número de WhatsApp asociado.
- No abrir salidas ni activar `WHATSAPP_OUTBOUND_ENABLED=true` sin nueva revisión específica.
- La rama derivada NO debe fusionarse ni desplegarse automáticamente sobre `main`, `api-image` u `outbox-worker`. Los servicios usan configuraciones de imagen distintas; hay que verificar y preservar recuperación antes de cualquier actualización.

## Próximos pasos
1. Separar despliegue de API, worker y calendario. Verificar rollback y consentimiento.
2. Implementar modo sugerencia para recepción: respuestas automáticas solo para FAQs validadas; consultas médicas y urgencias a personal humano.
3. Registrar un número de prueba autorizado por Meta y probar una recepción *sin envío*, en una fase expresamente aprobada.
4. Desplegar controles de salida en el trabajador que procesa producción antes de probar respuestas automatizadas.
5. Hacer la prueba auténtica del recorrido Meta → Core → DentalFlow y medir calidad/latencia.
