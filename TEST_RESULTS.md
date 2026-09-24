# LocalFlow Core v0.3 — Resultado de validación

Suite automatizada final:

**38 pruebas — PASS**

Cobertura funcional validada:
- workflow y selección por opciones;
- firma HMAC del webhook;
- parsing de mensajes;
- idempotencia;
- aislamiento multi-tenant;
- disponibilidad y duración por servicio;
- bloqueo de doble reserva;
- hold temporal y expiración;
- confirmación/cancelación;
- reprogramación segura;
- conservación de cita original hasta confirmar la nueva;
- handoff humano;
- reactivación de lead;
- reglas de urgencia;
- Google Calendar: freebusy, creación, colisión, idempotencia y eliminación diferida;
- recordatorios/reseñas con templates;
- cancelación de automatizaciones al cancelar/reprogramar;
- hora local y etiqueta humana en parámetros de recordatorio;
- validación de configuraciones demo.

Validaciones adicionales:
- compilación de módulos Python;
- importación de la aplicación;
- seed sobre base SQLite limpia;
- integridad del ZIP final.

Pendiente por diseño para un despliegue real:
- introducir credenciales reales;
- aprobar/configurar plantillas de Meta;
- configurar dominio HTTPS;
- conectar calendarios reales;
- backups/monitorización del entorno elegido.
