
"""Cliente mínimo de AgentMail para leer correos con solicitudes de vacante.

Solo usa httpx (no el SDK) para no agregar dependencias más allá de las que ya
requiere el proyecto. Funciona con el plan free de AgentMail.

Variables de entorno (.env):
- AGENTMAIL_API_KEY: API key de AgentMail (RNF-09: nunca se sube al repo).
- AGENTMAIL_INBOX_ID: bandeja que se consulta, p. ej. rachell-9884@agentmail.to.

Endpoints usados:
- GET /v0/inboxes/{inbox_id}/messages        -> lista de mensajes
- GET /v0/inboxes/{inbox_id}/messages/{id}   -> mensaje con cuerpo completo
"""

import base64
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx


URL_BASE = "https://api.agentmail.to/v0"
# Consultar más seguido que esto agotaría la cuota del plan free (RNF-09).
MIN_INTERVALO = 15.0
VARIABLE_API_KEY = "AGENTMAIL_API_KEY"
VARIABLE_INBOX = "AGENTMAIL_INBOX_ID"


class ErrorAgentMail(RuntimeError):
    """Error al comunicarse con la API de AgentMail."""


@dataclass
class Adjunto:
    attachment_id: str
    filename: str
    content_type: str
    content: bytes | None = None


@dataclass
class Correo:
    message_id: str
    thread_id: str
    remitente: str
    destinatarios: list[str]
    asunto: str
    fecha: str
    cuerpo: str
    adjuntos: list[Adjunto] = field(default_factory=list)

    @property
    def direccion_remitente(self) -> str:
        """Extrae 'usuario@dominio' de un remitente 'Nombre <usuario@dominio>'."""

        texto = (self.remitente or "").strip()
        if "<" in texto and ">" in texto:
            return texto[texto.index("<") + 1 : texto.rindex(">")].strip().lower()
        return texto.lower()


def _texto(valor: Any) -> str:
    return str(valor or "").strip()


def _a_correo(datos: dict, cuerpo_detallado: bool = False) -> Correo:
    adjuntos = [
        Adjunto(
            attachment_id=_texto(item.get("attachment_id")),
            filename=_texto(item.get("filename")),
            content_type=_texto(item.get("content_type")),
        )
        for item in (datos.get("attachments") or [])
    ]

    # En la lista viene `preview`; en el detalle hay `text` y `extracted_text`.
    cuerpo = ""
    if cuerpo_detallado:
        cuerpo = (
            _texto(datos.get("extracted_text"))
            or _texto(datos.get("text"))
            or _texto(datos.get("preview"))
        )
    else:
        cuerpo = _texto(datos.get("preview"))

    return Correo(
        message_id=_texto(datos.get("message_id")),
        thread_id=_texto(datos.get("thread_id")),
        remitente=_texto(datos.get("from")),
        destinatarios=[_texto(d) for d in (datos.get("to") or [])],
        asunto=_texto(datos.get("subject")),
        fecha=_texto(datos.get("timestamp")),
        cuerpo=cuerpo,
        adjuntos=adjuntos,
    )


class AgentMailCliente:
    """Cliente HTTP de AgentMail."""

    def __init__(
        self,
        api_key: str | None = None,
        inbox_id: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or os.getenv(VARIABLE_API_KEY, "")
        self.inbox_id = inbox_id or os.getenv(VARIABLE_INBOX, "")

        if not self.api_key:
            raise ErrorAgentMail(
                f"Falta {VARIABLE_API_KEY}. Se lee desde el archivo .env (RNF-09)."
            )
        if not self.inbox_id:
            raise ErrorAgentMail(
                f"Falta {VARIABLE_INBOX}. Indica la bandeja, por ejemplo rachell-9884@agentmail.to."
            )

        self._http = httpx.Client(
            base_url=URL_BASE,
            timeout=timeout,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )

    def __enter__(self) -> "AgentMailCliente":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.cerrar()

    def cerrar(self) -> None:
        self._http.close()

    # --- API de lectura ---

    def _get(self, ruta: str, **parametros: Any) -> dict:
        try:
            respuesta = self._http.get(ruta, params=parametros or None)
        except httpx.HTTPError as error:
            raise ErrorAgentMail(f"No se pudo conectar con AgentMail: {error}") from error

        if respuesta.status_code != 200:
            raise ErrorAgentMail(
                f"AgentMail respondió {respuesta.status_code} en {ruta}: "
                f"{respuesta.text[:300]}"
            )

        return respuesta.json()

    def listar_mensajes(
        self,
        limite: int = 10,
        remitente: str | None = None,
        asunto: str | None = None,
    ) -> list[Correo]:
        """Lista los mensajes más recientes de la bandeja (sin cuerpo completo)."""

        parametros: dict[str, Any] = {"limit": limite}
        if remitente:
            parametros["from"] = remitente
        if asunto:
            parametros["subject"] = asunto

        datos = self._get(f"/inboxes/{self.inbox_id}/messages", **parametros)
        return [_a_correo(item) for item in datos.get("messages", [])]

    def obtener_mensaje(self, message_id: str) -> Correo:
        """Devuelve un mensaje con su cuerpo completo (texto extraído)."""

        datos = self._get(f"/inboxes/{self.inbox_id}/messages/{message_id}")
        return _a_correo(datos, cuerpo_detallado=True)

    def descargar_adjunto(self, message_id: str, attachment_id: str) -> bytes:
        """Descarga el contenido de un adjunto (por ejemplo, un JSON de vacante)."""

        try:
            respuesta = self._http.get(
                f"/inboxes/{self.inbox_id}/messages/{message_id}"
                f"/attachments/{attachment_id}"
            )
        except httpx.HTTPError as error:
            raise ErrorAgentMail(f"No se pudo descargar el adjunto: {error}") from error

        if respuesta.status_code != 200:
            raise ErrorAgentMail(
                f"AgentMail respondió {respuesta.status_code} al descargar "
                f"el adjunto {attachment_id}."
            )

        try:
            datos = respuesta.json()
        except ValueError:
            return respuesta.content  # La API pudo devolver el binario directo.

        contenido = datos.get("content") if isinstance(datos, dict) else None
        if isinstance(contenido, str):
            return base64.b64decode(contenido)
        if isinstance(contenido, (bytes, bytearray)):
            return bytes(contenido)
        return respuesta.content

    # --- API de vigilancia ---

    def ids_recientes(self, limite: int = 10) -> set[str]:
        """IDs de los mensajes más recientes (sin descargar cuerpos ni adjuntos).

        La lista llega ordenada del más nuevo al más antiguo, así que pedir
        `limite` mensajes basta para detectar llegadas nuevas.
        """

        if limite < 1:
            raise ValueError("El límite debe ser al menos 1.")

        datos = self._get(f"/inboxes/{self.inbox_id}/messages", limit=limite)
        return {
            _texto(item.get("message_id"))
            for item in datos.get("messages", [])
            if _texto(item.get("message_id"))
        }

    def esperar_mensaje_nuevo(
        self,
        intervalo: float = 15.0,
        limite: int = 20,
        tiempo_maximo: float | None = None,
        max_errores_seguidos: int = 5,
        aviso: Callable[[str], None] | None = None,
    ) -> list[Correo]:
        """Consulta la bandeja periódicamente hasta que llegue un correo nuevo.

        Las respuestas HTTP se espacian lo necesario para no agotar la cuota
        del plan free de AgentMail. Los errores de red no detienen la
        vigilancia: se reintenta hasta `max_errores_seguidos` veces seguidas.

        Devuelve los correos nuevos (con cuerpo completo), del más antiguo al
        más reciente. Lanza TimeoutError si se supera `tiempo_maximo`.
        """

        if intervalo < MIN_INTERVALO:
            raise ValueError(
                f"El intervalo mínimo de consulta es {MIN_INTERVALO:g} segundos."
            )

        avisar = aviso or (lambda _mensaje: None)
        inicio = time.monotonic()
        conocidos = self.ids_recientes(limite=limite)
        errores_seguidos = 0

        avisar(
            f"Vigilando {self.inbox_id}: {len(conocidos)} mensaje(s) conocidos. "
            f"Consultando cada {intervalo:g} s…"
        )

        while True:
            if tiempo_maximo is not None and time.monotonic() - inicio >= tiempo_maximo:
                raise TimeoutError(
                    "No llegó ningún correo nuevo en "
                    f"{tiempo_maximo:g} segundos de vigilancia."
                )

            time.sleep(intervalo)

            try:
                actuales = self.ids_recientes(limite=limite)
            except ErrorAgentMail as error:
                errores_seguidos += 1
                avisar(
                    f"Error al consultar ({errores_seguidos}/{max_errores_seguidos}): "
                    f"{error}"
                )
                if errores_seguidos >= max_errores_seguidos:
                    raise
                continue

            errores_seguidos = 0
            nuevos = actuales - conocidos

            if nuevos:
                correos = [self.obtener_mensaje(mid) for mid in nuevos]
                correos.sort(key=lambda correo: correo.fecha)
                avisar(f"Correo(s) nuevo(s) detectado(s): {len(correos)}")
                return correos

            if actuales != conocidos:
                avisar("Cambiaron los mensajes recientes, pero no hay correos nuevos.")
            conocidos = actuales

    def buscar_solicitudes_vacante(self, limite: int = 10) -> list[Correo]:
        """Mensajes que parecen contener una solicitud de vacante (estructurada).

        Un correo cuenta si su cuerpo/asunto trae el JSON de vacante
        ("skills_obligatorios") o si adjunta un .json/.csv.
        """

        candidatos = []

        for mensaje in self.listar_mensajes(limite=limite):
            detalle = self.obtener_mensaje(mensaje.message_id)
            cuerpo = (detalle.cuerpo or "").lower()
            extensiones = {adj.filename.rsplit(".", 1)[-1].lower() for adj in detalle.adjuntos if "." in adj.filename}

            if (
                "skills_obligatorios" in cuerpo
                or "vacante" in (detalle.asunto or "").lower()
                or extensiones & {"json", "csv"}
            ):
                candidatos.append(detalle)

        return candidatos
