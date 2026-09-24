# Onboarding de un cliente en menos de 2 horas

Objetivo: dar de alta un negocio sin modificar el código base.

## Información que debe entregar el cliente antes de la sesión

- nombre comercial;
- zona horaria;
- teléfono de WhatsApp que se conectará;
- lista de servicios que sí se pueden agendar;
- duración de cada servicio;
- horarios;
- días cerrados;
- número de agendas/recursos (consultorio, especialista, cabina, etc.);
- URL de reseña de Google;
- texto de handoff;
- responsable humano de escalaciones;
- si usará Google Calendar, calendario correspondiente por recurso.

## Cronograma objetivo

### 0–20 min — Tenant
1. Copiar un JSON de `tenant_configs/`.
2. Cambiar `slug`, nombre, nicho y `phone_number_id`.
3. Definir variable de entorno del token de WhatsApp.
4. Verificar zona horaria.

### 20–50 min — Servicios y agenda
1. Cargar servicios.
2. Definir duración.
3. Definir recursos.
4. Cargar horarios semanales.
5. Cargar fechas cerradas.
6. Elegir `internal` o `google_calendar`.

### 50–75 min — Conversación
1. Ajustar saludo.
2. Ajustar opciones de servicio.
3. Configurar urgencia/handoff.
4. Revisar mensajes de confirmación/cancelación.

### 75–95 min — Automatizaciones
1. Cargar URL de reseña.
2. Configurar plantilla de recordatorio.
3. Configurar plantilla de reseña.
4. Mantener `enabled=false` hasta que Meta apruebe las plantillas.

### 95–120 min — Prueba de aceptación
Probar:
- mensaje inicial;
- opción inválida;
- urgencia;
- cita normal;
- doble reserva;
- confirmación;
- cancelación;
- reprogramación;
- handoff humano;
- reactivación;
- recordatorio/reseña;
- si usa Google: creación y eliminación del evento.

No se considera activado hasta que estas pruebas pasen.
