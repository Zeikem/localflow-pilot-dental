# LocalFlow — Playbook comercial y operativo

## Definición comercial

**LocalFlow instala un sistema de captación, atención y agendamiento para negocios locales que convierte consultas digitales en citas atendidas y con seguimiento.**

No se vende “un chatbot” ni “software”. Se vende:
- respuesta inmediata;
- menos consultas perdidas;
- agenda estructurada;
- seguimiento automático;
- recordatorios;
- solicitud de reseñas;
- escalamiento humano cuando el caso lo exige.

Mercado inicial: León, Guanajuato.
Vertical inicial: clínicas dentales.
Expansión prevista: ópticas y fisioterapia usando el mismo motor.

⚠️ [DETECCIÓN DE ERROR / OPTIMIZACIÓN]: Prometer posiciones concretas en Google Maps no depende por completo del proveedor y no debe formar parte de una garantía comercial.
-> [CORRECCIÓN APLICADA]: Vender optimización de presencia local + canal de contacto + atención/agendamiento automatizado. Nunca prometer “top 3” como resultado garantizado.

## Oferta inicial recomendada

### Implementación
Precio de partida sugerido: **$4,900 MXN**.

Incluye:
- alta del tenant;
- personalización de marca y textos;
- hasta 1 número de WhatsApp;
- hasta 1 ubicación;
- catálogo inicial de servicios;
- horarios y reglas de agenda;
- conexión con calendario interno o Google Calendar;
- flujo de cita;
- handoff humano;
- configuración de recordatorio y reseña cuando existan plantillas aprobadas;
- pruebas antes de salida.

### Mensualidad
Precio de partida sugerido: **$2,900 MXN/mes**.

Incluye:
- alojamiento/operación del sistema;
- monitoreo básico;
- mantenimiento de configuración;
- cambios menores de horarios/servicios;
- soporte;
- revisión mensual del flujo.

Estos precios son una **hipótesis comercial inicial**, no una estadística de mercado. Deben validarse con las primeras 10–20 conversaciones de venta.

⚠️ [DETECCIÓN DE ERROR / OPTIMIZACIÓN]: Cobrar $1,000 de setup y $1,500 mensuales puede dejar poco margen cuando ya existen onboarding técnico, soporte, infraestructura y mantenimiento.
-> [CORRECCIÓN APLICADA]: Mantener una oferta de entrada simple, pero con setup suficiente para pagar la implementación y una mensualidad que soporte operación recurrente.

## Flujo dental estándar

1. Entrada desde Google Maps, sitio, QR, anuncio o enlace.
2. WhatsApp recibe el mensaje.
3. El bot pide `nombre`.
4. Pregunta `servicio`.
5. Pregunta `urgencia`.
6. Si es urgente, deriva a humano sin intentar diagnóstico clínico.
7. Si no es urgente, consulta disponibilidad.
8. Presenta horarios.
9. Aparta temporalmente el horario.
10. Pide confirmación.
11. Confirma en la fuente de agenda.
12. Programa recordatorio.
13. Permite cancelar o reprogramar.
14. Después de la cita, programa solicitud de reseña si la automatización está habilitada.

### Variables estándar

- `tenant_id`
- `lead_id`
- `wa_id`
- `nombre`
- `servicio`
- `urgencia`
- `resource_key`
- `fecha_cita`
- `estado_lead`
- `appointment_id`
- `external_event_id`
- `status`
- `google_review_url`

La personalización por cliente debe quedar principalmente en configuración: marca, servicios, duración, horarios, recursos, textos, plantillas y enlaces.

## Prospección en León

### Contacto breve

“Hola, ¿qué tal? Estaba revisando cómo atienden las consultas que llegan por internet. Estoy implementando en León un sistema que responde por WhatsApp, filtra la solicitud y puede llevar al paciente directo a una cita disponible. No vengo a ofrecer manejo de redes. Si le parece, le enseño en unos minutos cómo quedaría aplicado a su clínica.”

### Objeciones

**“Ya tengo quien me maneje redes.”**  
“Perfecto; no sustituye ese trabajo. Esto se enfoca en la parte posterior: cuando una persona ya pregunta, el sistema la atiende, recopila lo necesario y la lleva a una cita o a recepción.”

**“Está muy caro.”**  
“Lo correcto es compararlo con el valor de consultas que hoy quedan sin respuesta o sin seguimiento. Primero revisamos cuántas consultas reciben y cuánto vale una cita nueva; si los números no justifican el sistema, no tendría sentido implementarlo.”

**“Mis clientes no usan WhatsApp.”**  
“Lo validamos antes de venderle nada. Si sus consultas realmente llegan por llamada u otro canal, adapto el diagnóstico; no conviene imponer WhatsApp si no es un canal real para su negocio.”

## Rutina diaria

- 30–45 min: seleccionar prospectos y revisar su atención digital.
- 30 min: contactos iniciales.
- 30 min: seguimientos.
- Bloque separado: demos, cierres y onboardings.
- Una vez por semana: revisar errores/reintentos y métricas operativas de clientes activos.

## Objetivo de escalabilidad

Mantener **80–90% del motor común** y limitar el **10–20%** variable a:
- textos;
- servicios;
- horarios;
- duración;
- recursos/calendarios;
- reglas de handoff;
- enlaces;
- plantillas aprobadas.

Si un cliente exige código especial para una necesidad no reusable, debe evaluarse como add-on o descartarse.
