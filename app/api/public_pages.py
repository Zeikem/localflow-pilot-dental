"""Public information pages for the LocalFlow pilot, no authentication or tracking."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["informacion-publica"])

_EMAIL = "rthojalateriaypintura@gmail.com"

def _page(title: str, body: str) -> HTMLResponse:
    markup = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ | LocalFlow</title>
<style>
:root{color-scheme:light}body{margin:0;background:#f5f7fa;color:#182331;
font:16px/1.65 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:790px;margin:40px auto;padding:30px;background:white;
border-radius:15px;box-shadow:0 3px 30px #14223715}
h1,h2{line-height:1.25}h1{font-size:2rem}h2{font-size:1.15rem;margin-top:30px}
a{color:#1258a1}footer{border-top:1px solid #ddd;margin-top:32px;padding-top:16px}
</style></head><body><main><h1>__TITLE__</h1>__BODY__
<footer><p>LocalFlow · Proyecto en fase piloto · León, Guanajuato, México</p>
<p><a href="/privacy">Privacidad</a> · <a href="/data-deletion">Eliminar datos</a>
 · <a href="/terms">Condiciones de uso</a></p></footer></main></body></html>"""
    return HTMLResponse(markup.replace("__TITLE__", title).replace("__BODY__", body),
                        headers={"Cache-Control": "public, max-age=300"})

@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
def privacy_policy():
    return _page("Aviso de privacidad de LocalFlow", """
<p><strong>Actualizado:</strong> 19 de octubre de 2026.</p>
<p><strong>Responsable del contacto sobre privacidad:</strong> LocalFlow,
proyecto tecnológico en etapa piloto en León, Guanajuato, México.
Correo: <a href="mailto:rthojalateriaypintura@gmail.com">rthojalateriaypintura@gmail.com</a>.
LocalFlow es el nombre público del proyecto, no una declaración de constitución
como sociedad mercantil.</p>
<h2>1. Alcance</h2>
<p>Este aviso se aplica al uso de la aplicación LocalFlow con las tecnologías de Meta y
WhatsApp para recibir solicitudes administrativas de prueba, comprobar integraciones
y asistir al personal de recepción de clínicas. La app no presta diagnóstico ni
atención médica.</p>
<h2>2. Datos que pueden recibirse</h2>
<p>Al interactuar con un número conectado mediante WhatsApp Business Platform, Meta
puede remitir temporalmente datos como identificador del mensaje, identificador de
WhatsApp del remitente, nombre de perfil, tipo de mensaje, texto y metadatos técnicos.
Los servidores de alojamiento también pueden tratar datos técnicos de conexión,
incluida la dirección IP, para operación y seguridad.</p>
<p><strong>En el piloto actual configurado como «solo recepción»:</strong>
antes de almacenarlos, el sistema reemplaza el identificador del remitente y del
mensaje por huellas criptográficas seudónimas. Conserva únicamente el tipo
administrativo de evento, marca de tiempo, identificadores seudónimos y estado
de revisión humana. El texto, nombre, número original y adjuntos no se guardan
en esa modalidad, ni se envía una respuesta automática.</p>
<h2>3. Finalidad y uso</h2>
<p>Los datos se utilizan para comprobar entregas de WhatsApp, identificar eventos
duplicados, mostrar solicitudes pendientes al personal autorizado, mantener la
seguridad del servicio y resolver errores operativos. En una futura implantación
con una clínica, el tratamiento adicional de datos de pacientes requerirá un
aviso y acuerdos específicos, así como revisión de los permisos y necesidades reales.</p>
<h2>4. Proveedores y transferencias</h2>
<p>Para el transporte de mensajes intervienen Meta y WhatsApp. Para operar el
servidor se utiliza Railway; el código se administra mediante GitHub.
No se utilizan los mensajes entrantes para entrenar modelos de IA.
El copiloto opcional de borradores administrativos solo utiliza categorías y
datos públicos previamente verificados, y permanece desconectado del contenido
privado de WhatsApp. Cada proveedor trata los datos conforme a sus propios términos
y acuerdos aplicables.</p>
<h2>5. Conservación y seguridad</h2>
<p>Los metadatos seudónimos se conservan mientras sean necesarios para la finalidad
de supervisión y seguridad del piloto, sujetos a revisión y eliminación cuando
corresponda. Se aplican controles de acceso, validación de firmas y claves privadas.
Ningún sistema ofrece seguridad absoluta. Si un registro es indispensable por
obligación legal, se conservará únicamente en los términos de dicha obligación.</p>
<h2>6. Acceso, rectificación, cancelación, oposición y eliminación</h2>
<p>Para ejercer los derechos de privacidad aplicables, solicitar eliminación de
datos o formular dudas, escribe a
<a href="mailto:rthojalateriaypintura@gmail.com">rthojalateriaypintura@gmail.com</a>
con el asunto «Privacidad LocalFlow». Explica tu solicitud e indica la información
mínima necesaria para localizar el registro, sin adjuntar datos médicos.
Podremos pedir medios razonables de verificación de titularidad y responderemos
conforme a los plazos y obligaciones legales aplicables.</p>
<p>Consulta también las <a href="/data-deletion">instrucciones para eliminar datos</a>.</p>
<h2>7. Cambios al aviso</h2>
<p>Si cambian las funciones o el tratamiento de datos, actualizaremos este aviso
antes de habilitar nuevas modalidades de atención y publicaremos la fecha
de la modificación.</p>
""")

@router.get("/data-deletion", response_class=HTMLResponse, include_in_schema=False)
def data_deletion():
    return _page("Solicitud de eliminación de datos", """
<p>Para solicitar el acceso, la revisión o eliminación de datos relacionados con
LocalFlow, envía un mensaje a
<a href="mailto:rthojalateriaypintura@gmail.com">rthojalateriaypintura@gmail.com</a>
con asunto <strong>Eliminar datos LocalFlow</strong>.</p>
<p>Indica que utilizaste el piloto de WhatsApp, la fecha aproximada y un medio
de contacto para responder. No incluyas documentación médica ni contraseñas.
El equipo revisará los registros bajo su control, verificará la titularidad cuando
sea necesario y comunicará el resultado o las limitaciones legales aplicables.
Las eliminaciones en Meta o WhatsApp se rigen además por sus propias opciones
y políticas; solicitar eliminación a LocalFlow no elimina automáticamente la
copia de una conversación que otra persona tenga en WhatsApp.</p>
<p>Los identificadores seudónimos del piloto no permiten reconstruir por sí mismos
un teléfono. Si no es posible identificar de manera razonable un registro,
se explicará esa limitación al solicitante.</p>
""")

@router.get("/terms", response_class=HTMLResponse, include_in_schema=False)
def terms():
    return _page("Condiciones de uso de LocalFlow", """
<p><strong>Actualizado:</strong> 19 de octubre de 2026.</p>
<p>LocalFlow es una herramienta tecnológica en fase piloto para organizar
consultas administrativas recibidas por canales autorizados. El acceso a
sus funciones internas corresponde únicamente a usuarios habilitados.</p>
<p>El sistema no sustituye al personal de una clínica, no ofrece diagnósticos
ni confirma citas por el mero hecho de preparar un borrador. Las propuestas
del copiloto requieren revisión humana y verificación de la disponibilidad
antes de utilizarse. Las comunicaciones por WhatsApp se sujetan a los permisos,
restricciones y políticas de Meta y WhatsApp.</p>
<p>No se autoriza utilizar la herramienta para envíos no solicitados,
suplantación, tratamiento de información clínica sin base legal ni actos
contrarios a las leyes aplicables.</p>
<p>Contacto sobre estas condiciones:
<a href="mailto:rthojalateriaypintura@gmail.com">rthojalateriaypintura@gmail.com</a>.</p>
""")
