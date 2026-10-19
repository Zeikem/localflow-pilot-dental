# Copiloto administrativo de LocalFlow Core: MVP sin envíos

## Alcance implementado
Nuevo endpoint autenticado `POST /admin/copilot/draft` para preparar **borradores de texto destinados a una persona de recepción**. No examina webhooks ni conversaciones de pacientes. No crea oportunidades, citas ni mensajes salientes.

Solicitudes admitidas:
```json
{
  "intent": "horarios",
  "verified_public_fact": "lunes a viernes de 9 a 18",
  "request_ai": false
}
```
Las opciones de `intent` son `saludo, horarios, servicios, precios, agendar, reprogramar, cancelar, urgencia, otro`. El dato público tiene límite de 160 caracteres y se rechazan teléfonos, emails, URLs, vocabulario clínico y formas comunes de inyección de instrucciones.

Respuesta:
```json
{
  "draft": "Nuestros horarios confirmados son: lunes a viernes de 9 a 18. Recepción puede ayudarte con más detalles.",
  "source": "plantilla",
  "requires_human_review": true,
  "sent": false,
  "appointment_created": false,
  "api_called": false
}
```

## Seguridad, privacidad y costes
- Requiere credencial exclusiva de 32+ caracteres `LOCALFLOW_COPILOT_TOKEN` por cabecera `X-LocalFlow-Copilot-Token`. Sin configurar, responde 503. No reutilizar credencial administrativa, bridge token ni secreto de Meta.
- Por defecto `LOCALFLOW_AI_ENABLED=false`, `LOCALFLOW_AI_API_KEY` sin valor. Por tanto, cero llamadas facturables.
- Incluso con `request_ai=true`, solo se genera mediante API cuando también están habilitados el interruptor del servidor, un modelo válido y la clave de API.
- La integración opcional usa la API **Responses** de OpenAI con `store=false`, `max_output_tokens=160` y `timeout=8s`. **Puede generar cargos** cuando se habilite; revisar facturación y establecer límites en el panel de OpenAI antes de usar. No hay cuota diaria persistente aquí; **NO** asumir que el límite de tokens por respuesta es límite de gasto total.
- Solo se envía categoría + información **pública verificada**. Nunca nombres, transcripciones, teléfonos, datos clínicos o eventos de WhatsApp.
- La salida de IA es SIEMPRE un borrador para revisión humana, no una acción ejecutada. Temas urgentes, reservas, cancelaciones y reprogramaciones usan textos fijos sin llamadas al modelo. Si la API falla, vuelve a una plantilla.
- No guarda los borradores, no tiene acción de envío ni conexión con el worker.
- Este control no prueba que el sistema responda automáticamente a WhatsApp ni que exista una agenda unificada.

## Uso desde DentalFlow
En el panel Windows existente `/asistente/` se añadió la sección `Copiloto de LocalFlow Core`, junto a los métodos locales ya presentes. Sin duplicar interfaz.

Solo tras un despliegue autorizado del endpoint y una credencial independiente compartida entre Railway y el archivo privado de Windows:
- Railway `api-image`: `LOCALFLOW_COPILOT_TOKEN`.
- Windows DentalFlow `.env`: `LOCALFLOW_CORE_COPILOT_TOKEN` con el mismo valor.
- La URL fija es `https://api-image-production-7f8d.up.railway.app`; no admitir otros hosts.
- El usuario elige una categoría y, opcionalmente, aporta un hecho público confirmado. La pantalla muestra un BORRADOR SIN ENVIAR. No requiere créditos mientras el modelo está desactivado.

## Pruebas
10 pruebas nuevas del Core verificadas en un entorno aislado; GitHub CI debe finalizar en verde. En Windows se ejecutaron 89 pruebas de Core con resultado OK.
Se añadieron pruebas separadas del cliente Django para autenticación, datos personales, servidor fijo, controles de seguridad y no persistencia.

## Estado
Esta rama parte de `feature/inbound-review-only-20261019`. **No fusionar a main** sin el plan de despliegue y respaldo. El modo WhatsApp de solo recepción permanece intacto; conectar IA directamente a mensajes reales requerirá consentimiento, minimización de datos y una arquitectura distinta.
