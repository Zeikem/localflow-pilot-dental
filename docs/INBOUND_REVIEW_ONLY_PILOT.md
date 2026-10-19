# LocalFlow Dental | Modo recepción segura sin respuestas

Fecha de desarrollo: 2026-10-19. **NO DESPLEGADO ni habilitado para Meta**.

## Qué hace
Para una clínica con `workflow_spec.inbound_mode = "review_only"`:
- Acepta mensajes de Meta que superen la verificación HMAC del webhook y coincidan con el identificador de número registrado.
- Registra solo el tipo permitido y la hora, una huella HMAC del evento y una huella HMAC truncada y estable del remitente; el contacto queda marcado para recepción humana.
- Descarta inmediatamente texto del mensaje, teléfono, nombre de WhatsApp, adjuntos y JSON original. No guarda esos campos en la base.
- No llama al motor de conversación, ni ofrece horarios, ni reserva citas, ni genera mensajes pendientes.
- Deduplica eventos: si hay un conflicto de unicidad, revierte y reintenta una vez. Si se sigue sin poder guardar, responde HTTP 503 para que Meta reintente en lugar de reconocer una entrega perdida. Un duplicado real no crea nuevas filas.
- Si falta `LOCALFLOW_INBOUND_PSEUDONYM_KEY` de al menos 32 bytes, responde HTTP 503 sin guardar datos ni aceptar el mensaje. Meta puede reintentar.
- Rechaza firmas inválidas, así como cuerpos superiores a 128 KiB.
- Con un token de lectura válido y la clínica autorizada, el puente `GET /admin/bridge/events` muestra solo «Requiere recepción».

**Los identificadores originales de Meta y el teléfono NO aparecen en el puente ni en los nuevos registros de este modo.** El hash no sirve para enviar mensajes al usuario. Esto es intencional para la etapa de recepción y privacidad.

## Defensa en profundidad de salida
1. `WHATSAPP_OUTBOUND_ENABLED=false` permanece como valor predeterminado del cliente y el trabajador (de la rama previa).
2. Aun con este valor en true, `WhatsAppClient.send_text` y `send_template` rechazan cualquier tenant con `inbound_mode=review_only`.
3. Si había una salida en cola para ese tenant, el trabajador actualizado la marca `blocked`, sin hablar con Meta.

Estas protecciones **solo existen cuando tanto API como worker ejecutan las nuevas versiones**. Actualmente Railway todavía ejecuta la versión anterior del trabajador y NO se ha asociado el número de prueba al tenant.

## Pruebas
```powershell
cd C:\Users\Usuario\Documents\LocalFlow-Core-Bridge-20261019\localflow-pilot-dental-main
..\.venv\Scripts\python.exe -m unittest discover -s tests -q
```
Resultado local: **81/81 pruebas aprobadas**, sin llamadas a WhatsApp real. Hay cobertura de modo solo recepción, firmas, faltas de secreto, duplicación, medios, tamaño, filtrado de datos personales, rutas protegidas, agenda y barreras de envío. La batería previa de conversación asistida también pasa.

## Secuencia de activación futura, todavía NO autorizada ni ejecutada
1. Revisar cambios de la rama derivada de PR #8; planificar reversión y revisar que no haya trabajo real en la cola.
2. Publicar de manera controlada tanto API `api-image` como `outbox-worker`, sin encender el envío. Verificar salud y firma del webhook sin modificar callback de Meta.
3. Configurar exclusivamente en el API una clave privada independiente `LOCALFLOW_INBOUND_PSEUDONYM_KEY` de 32+ bytes. No colocarla en GitHub, chat, capturas ni paquetes.
4. Cambiar **solo el tenant piloto** a `workflow_spec.inbound_mode=review_only`, sin otros pasos de flujo, agenda ni salidas habilitadas.
5. Tras autorización específica, asociar únicamente el **Phone Number ID de prueba** de Meta y confirmar los permisos.
6. Hacer una prueba con un número propio autorizado, constatar HTTP 200 y la nueva señal anónima en DentalFlow; confirmar cero nuevos mensajes en la cola, cero envíos y cero reservas.
7. No utilizar pacientes reales ni dar por finalizado un bot de IA por esta prueba. El siguiente modo requerirá consentimiento, rutas seguras de respuesta, supervisión humana y una agenda única.

## Límites
- No transcribe mensajes ni permite responder desde una señal anónima.
- No genera respuestas de IA ni procesa información clínica.
- Un mensaje sin número asociado no se vincula a la clínica y no crea registros.
- Las colas globales de otros tenants conservan su comportamiento preexistente hasta cambiar sus modos.
- No constituye un servicio clínico listo para operar, ni autorización para enviar mensajes.

Esta fase prueba **recepción segura sin acción saliente**, no automatización comercial completa.
