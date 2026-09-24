# Plantillas de WhatsApp requeridas

Los mensajes programados fuera de una conversación activa deben prepararse como plantillas aprobadas por Meta cuando corresponda.

LocalFlow espera por defecto dos plantillas configurables por tenant.

## 1. Recordatorio

Nombre sugerido: `recordatorio_cita_localflow`

Parámetros de cuerpo, en orden:
1. nombre del cliente;
2. servicio;
3. fecha/hora local de la cita.

Ejemplo conceptual:
“Hola {{1}}. Te recordamos tu cita de {{2}} para {{3}}. Si necesitas cambiarla, responde a este mensaje.”

## 2. Solicitud de reseña

Nombre sugerido: `solicitud_resena_localflow`

Parámetros:
1. nombre;
2. enlace de reseña de Google.

Ejemplo conceptual:
“Hola {{1}}. Gracias por visitarnos. Si deseas compartir tu experiencia, puedes hacerlo aquí: {{2}}.”

## Regla de activación

En los JSON demo las automatizaciones deben permanecer deshabilitadas hasta:
- tener consentimiento/proceso de mensajería correcto;
- tener plantillas aprobadas;
- cargar los nombres exactos de plantilla;
- probar el envío en el número real.

Los nombres de ejemplo no implican que Meta ya los haya aprobado.
