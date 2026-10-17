# LocalFlow: demostración local de reservas (piloto dental)

Esta demostración **ejecuta el motor real de conversación y reservas** con un
calendario interno y una base de datos **SQLite en memoria**. Los datos del
paciente y el número de WhatsApp son ficticios.

**No comprueba la integración con Meta ni Google Calendar. No envía mensajes.**
Su propósito es demostrar el flujo actual del software sin tocar producción.

## Ejecutar

En el repositorio, con Python 3.12 y el proyecto instalado:

```powershell
python -m pip install .
python -m app.demo
```

Para guardar evidencia estructurada:

```powershell
python -m app.demo --json > evidencia_demo.json
```

El archivo JSON contiene solamente el ejemplo ficticio y el estado de la cita.
No contiene credenciales, identificadores de pacientes reales ni respuestas de
un servicio externo.

## Guion del ejemplo

1. Paciente escribe «Hola» y el sistema solicita su nombre.
2. Paciente indica «Sofía» y el sistema ofrece servicios.
3. Paciente elige «1» (valoración).
4. Paciente indica «2» (no urgente).
5. El sistema muestra horarios libres de una **agenda interna de prueba**.
6. Paciente elige «1» y luego «CONFIRMAR».
7. El programa comprueba que existe exactamente **una** cita confirmada.

El script detiene su ejecución si alguno de los pasos falla.

## Verificación automática

```powershell
python -m unittest discover -s tests -v
python -m app.demo --json
```

## Pendientes para una demostración real

- Acceso autorizado a Meta Developers para comprobar callback, WABA y evento `messages`.
- Webhook entrante verificado con una conversación real de un número autorizado.
- Respuesta saliente entregada por `outbox-worker`, con registro de resultado.
- Credenciales de servicio y calendario **de prueba, no personal** para Google Calendar.
- Prueba de reserva, confirmación, cancelación, reprogramación y escalación humana
  con un contacto de prueba.
- Aprobación y despliegue controlado de los cambios tras revisar CI y seguridad.

El repositorio de ejemplo usa `google_calendar` en la configuración dental.
Esta demostración sobrescribe solamente la **copia en memoria** de esa configuración
para utilizar el calendario `internal`. No ejecuta `app.seed`, no modifica la
configuración almacenada y no escribe en Railway o en el calendario real.
