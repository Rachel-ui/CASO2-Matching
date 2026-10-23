
"""Pruebas del cliente de AgentMail con respuestas simuladas.

No consumen cuota del plan free: sustituyen el transporte HTTP por
httpx.MockTransport y verifican URL, autenticación y parseo de la respuesta.
"""

import base64
import json

import httpx
import pytest

from src.agentmail_cliente import AgentMailCliente, ErrorAgentMail


INBOX = "rachell-9884@agentmail.to"

LISTA = {
    "count": 2,
    "limit": 10,
    "messages": [
        {
            "inbox_id": INBOX,
            "thread_id": "t1",
            "message_id": "m1",
            "labels": [],
            "timestamp": "2026-10-19T10:00:00Z",
            "from": "RRHH Ejemplo <rrhh@example.com>",
            "to": [INBOX],
            "size": 1200,
            "updated_at": "2026-10-19T10:00:00Z",
            "created_at": "2026-10-19T10:00:00Z",
            "subject": "Solicitud de vacante V001",
            "preview": "Adjunto la vacante...",
            "attachments": [
                {
                    "attachment_id": "att1",
                    "size": 300,
                    "filename": "vacante.json",
                    "content_type": "application/json",
                }
            ],
        },
        {
            "inbox_id": INBOX,
            "thread_id": "t2",
            "message_id": "m2",
            "labels": [],
            "timestamp": "2026-10-19T09:00:00Z",
            "from": "newsletter@example.com",
            "to": [INBOX],
            "size": 400,
            "updated_at": "2026-10-19T09:00:00Z",
            "created_at": "2026-10-19T09:00:00Z",
            "subject": "Boletín semanal",
            "preview": "Novedades de la semana",
        },
    ],
}

DETALLE = {
    **LISTA["messages"][0],
    "text": "Texto plano",
    "extracted_text": '{"id": "V001", "skills_obligatorios": ["Python", "SQL"]}',
}

ADJUNTO = {
    "attachment_id": "att1",
    "size": 300,
    "filename": "vacante.json",
    "content_type": "application/json",
    "content": base64.b64encode(b'{"id": "V001"}').decode(),
}


@pytest.fixture
def pedidos():
    return []


@pytest.fixture
def cliente(pedidos):
    def responder(peticion: httpx.Request) -> httpx.Response:
        pedidos.append(peticion)
        ruta = peticion.url.path

        if peticion.headers.get("Authorization") != "Bearer clave-de-prueba":
            return httpx.Response(401, json={"message": "No autorizado"})
        if ruta == f"/v0/inboxes/{INBOX}/messages":
            return httpx.Response(200, json=LISTA)
        if ruta == f"/v0/inboxes/{INBOX}/messages/m1":
            return httpx.Response(200, json=DETALLE)
        if ruta == f"/v0/inboxes/{INBOX}/messages/m1/attachments/att1":
            return httpx.Response(200, json=ADJUNTO)
        if ruta == f"/v0/inboxes/{INBOX}/messages/m2":
            return httpx.Response(
                200, json={**LISTA["messages"][1], "text": "Novedades de la semana"}
            )
        return httpx.Response(404, json={"message": "No encontrado"})

    creado = AgentMailCliente(api_key="clave-de-prueba", inbox_id=INBOX)
    creado._http = httpx.Client(
        base_url="https://api.agentmail.to/v0",
        headers={"Authorization": "Bearer clave-de-prueba"},
        transport=httpx.MockTransport(responder),
    )
    yield creado
    creado.cerrar()


def test_exige_api_key(monkeypatch):
    monkeypatch.delenv("AGENTMAIL_API_KEY", raising=False)

    with pytest.raises(ErrorAgentMail, match="AGENTMAIL_API_KEY"):
        AgentMailCliente(inbox_id=INBOX)


def test_exige_inbox_id(monkeypatch):
    monkeypatch.delenv("AGENTMAIL_INBOX_ID", raising=False)

    with pytest.raises(ErrorAgentMail, match="AGENTMAIL_INBOX_ID"):
        AgentMailCliente(api_key="clave-de-prueba")


def test_lista_mensajes(cliente, pedidos):
    mensajes = cliente.listar_mensajes(limite=5)

    assert len(mensajes) == 2
    assert mensajes[0].message_id == "m1"
    assert mensajes[0].asunto == "Solicitud de vacante V001"
    assert mensajes[0].direccion_remitente == "rrhh@example.com"
    assert mensajes[0].adjuntos[0].filename == "vacante.json"
    assert pedidos[0].url.params["limit"] == "5"


def test_obtiene_cuerpo_completo(cliente):
    correo = cliente.obtener_mensaje("m1")

    # Se prefiere extracted_text sobre text y preview.
    assert correo.cuerpo.startswith('{"id": "V001"')
    assert json.loads(correo.cuerpo)["skills_obligatorios"] == ["Python", "SQL"]


def test_descarga_adjunto(cliente):
    contenido = cliente.descargar_adjunto("m1", "att1")

    assert json.loads(contenido)["id"] == "V001"


def test_busca_solo_correos_con_vacante(cliente):
    solicitudes = cliente.buscar_solicitudes_vacante(limite=10)

    assert [correo.message_id for correo in solicitudes] == ["m1"]


def test_error_http_se_informa():
    cliente = AgentMailCliente(api_key="clave-incorrecta", inbox_id=INBOX)
    cliente._http = httpx.Client(
        base_url="https://api.agentmail.to/v0",
        transport=httpx.MockTransport(
            lambda _peticion: httpx.Response(401, text="No autorizado")
        ),
    )

    with pytest.raises(ErrorAgentMail, match="401"):
        cliente.listar_mensajes()


def _cliente_vigilancia(respuestas):
    """Cliente simulado: cada consulta a la lista devuelve el siguiente estado."""

    estado = {"consultas": 0}

    def responder(peticion: httpx.Request) -> httpx.Response:
        ruta = peticion.url.path
        if ruta == f"/v0/inboxes/{INBOX}/messages":
            indice = min(estado["consultas"], len(respuestas) - 1)
            estado["consultas"] += 1
            respuesta = respuestas[indice]
            if isinstance(respuesta, Exception):
                raise respuesta
            return respuesta

        if ruta == f"/v0/inboxes/{INBOX}/messages/m3":
            return httpx.Response(
                200,
                json={
                    "message_id": "m3",
                    "thread_id": "t3",
                    "timestamp": "2026-10-20T08:00:00Z",
                    "from": "RRHH <rrhh@example.com>",
                    "to": [INBOX],
                    "subject": "Nueva solicitud",
                    "extracted_text": "Contenido nuevo",
                },
            )
        return httpx.Response(404, json={"message": "No encontrado"})

    creado = AgentMailCliente(api_key="clave-de-prueba", inbox_id=INBOX)
    creado._http = httpx.Client(
        base_url="https://api.agentmail.to/v0",
        transport=httpx.MockTransport(responder),
    )
    return creado, estado


def test_vigilancia_devuelve_el_correo_nuevo(monkeypatch):
    monkeypatch.setattr("src.agentmail_cliente.time.sleep", lambda _s: None)

    nuevo = {
        "count": 1,
        "limit": 20,
        "messages": [{"message_id": "m3", "timestamp": "2026-10-20T08:00:00Z"}],
    }
    cliente, estado = _cliente_vigilancia(
        [httpx.Response(200, json=LISTA), httpx.Response(200, json=LISTA), httpx.Response(200, json=nuevo)]
    )
    avisos = []

    correos = cliente.esperar_mensaje_nuevo(intervalo=15, aviso=avisos.append)

    assert [correo.message_id for correo in correos] == ["m3"]
    assert correos[0].cuerpo == "Contenido nuevo"
    # Una consulta inicial + dos esperas antes de detectar el mensaje.
    assert estado["consultas"] == 3
    assert any("nuevo(s) detectado(s)" in aviso for aviso in avisos)


def test_vigilancia_reintenta_errores_de_red(monkeypatch):
    monkeypatch.setattr("src.agentmail_cliente.time.sleep", lambda _s: None)

    nuevo = {
        "count": 1,
        "limit": 20,
        "messages": [{"message_id": "m3", "timestamp": "2026-10-20T08:00:00Z"}],
    }
    cliente, _ = _cliente_vigilancia(
        [
            httpx.Response(200, json=LISTA),
            httpx.Response(503, text="No disponible"),
            httpx.Response(200, json=nuevo),
        ]
    )

    correos = cliente.esperar_mensaje_nuevo(intervalo=15)

    assert [correo.message_id for correo in correos] == ["m3"]


def test_vigilancia_rechaza_intervalos_cortos(cliente):
    with pytest.raises(ValueError, match="intervalo mínimo"):
        cliente.esperar_mensaje_nuevo(intervalo=1)


def test_vigilancia_respeta_tiempo_maximo(monkeypatch):
    monkeypatch.setattr("src.agentmail_cliente.time.sleep", lambda _s: None)
    cliente, _ = _cliente_vigilancia([httpx.Response(200, json=LISTA)])

    with pytest.raises(TimeoutError, match="No llegó ningún correo nuevo"):
        cliente.esperar_mensaje_nuevo(intervalo=15, tiempo_maximo=0)
