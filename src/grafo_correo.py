
"""Nodo de LangGraph que interpreta un correo y decide qué hacer con él.

Se usa como un grafo pequeño y aparte del de matching:

    START -> interpretar_correo -> (guardar_vacante | guardar_candidato | descartar) -> END

`interpretar_correo` detecta si el texto libre describe una vacante o un
candidato y extrae sus campos; el nodo de guardado deja el dato ordenado en
`data/` y, si es una vacante, corre el matching para ver quién queda en los
puestos.
"""

from typing import TypedDict

from langgraph.graph import START, END, StateGraph

from src.agentmail_cliente import Correo
from src.interpretar_texto import (
    TIPO_CANDIDATO,
    TIPO_DESCONOCIDO,
    TIPO_VACANTE,
    TextoInterpretado,
    interpretar,
)


class EstadoCorreo(TypedDict, total=False):
    """Estado del grafo de interpretación de un correo."""

    correo: Correo
    texto: str
    # Vacante ya estructurada (bandeja simulada): si viene, se guarda tal
    # cual, sin reinterpretar el texto (RF-15).
    vacante: dict
    tipo: str
    datos: dict
    pistas: list[str]
    advertencias: list[str]
    interpretado: object
    accion: str
    resultado: dict
    errores: list[str]
    auditoria: list[dict]


def _evento(estado: EstadoCorreo, nodo: str, decision: str, motivo: str) -> list[dict]:
    return estado.get("auditoria", []) + [
        {"nodo": nodo, "decision": decision, "motivo": motivo}
    ]


def interpretar_correo(estado: EstadoCorreo) -> dict:
    """Detecta si el correo es vacante o candidato y extrae sus campos.

    Si el correo ya trae la vacante estructurada, se usa esa: es el disparador
    del matching aunque el texto no alcance para reconstruirla.
    """

    vacante = estado.get("vacante") or {}
    if vacante.get("id") and vacante.get("skills_obligatorios"):
        return {
            "tipo": TIPO_VACANTE,
            "datos": vacante,
            "pistas": [],
            "advertencias": [],
            "interpretado": None,
            "auditoria": _evento(
                estado,
                "interpretar_correo",
                TIPO_VACANTE,
                f"El correo trae la vacante estructurada {vacante['id']}; se usa tal cual.",
            ),
        }

    interpretado: TextoInterpretado = interpretar(estado["texto"])

    if interpretado.tipo == TIPO_VACANTE:
        motivo = "El texto describe una vacante."
    elif interpretado.tipo == TIPO_CANDIDATO:
        motivo = "El texto describe a un candidato."
    else:
        motivo = "No se pudo clasificar el texto: no describe ni un cargo ni un perfil."

    senales = [
        f"{grupo}: {oracion}"
        for grupo, oraciones in interpretado.evidencia.items()
        for oracion in oraciones[:1]
    ]
    if senales:
        motivo += " Contexto: " + "; ".join(senales[:3]) + "."
    if interpretado.advertencias:
        motivo += f" Datos faltantes: {'; '.join(interpretado.advertencias)}."

    return {
        "tipo": interpretado.tipo,
        "datos": interpretado.datos,
        "pistas": interpretado.pistas,
        "advertencias": interpretado.advertencias,
        "interpretado": interpretado,
        "auditoria": _evento(estado, "interpretar_correo", interpretado.tipo, motivo),
    }


def _registrar(estado: EstadoCorreo, accion: str, identificador: str = "") -> None:
    """Deja constancia del correo en data/correos_recibidos.csv."""

    from src.registro_correos import registrar_correo

    if estado.get("interpretado") is None:
        # La vacante venía estructurada: se registra con un texto mínimo.
        from src.interpretar_texto import TextoInterpretado

        estado = {
            **estado,
            "interpretado": TextoInterpretado(
                tipo=TIPO_VACANTE,
                datos=estado["datos"],
                pistas=[],
                advertencias=[],
                evidencia={},
            ),
        }

    try:
        registrar_correo(
            estado["correo"],
            estado["interpretado"],
            accion=accion,
            identificador=identificador,
        )
    except OSError as error:
        print(f"No se pudo registrar el correo en el CSV: {error}")


def guardar_vacante_nodo(estado: EstadoCorreo) -> dict:
    """Guarda la vacante y ejecuta el matching para actualizar los 3 puestos."""

    from src import procesar_correo as modulo_procesar_correo
    from src.solicitud_vacante import ErrorVacante, validar_vacante

    vacante = estado["datos"]
    problemas = validar_vacante(vacante)

    if problemas:
        _registrar(estado, "revision_humana", vacante.get("id", ""))
        return {
            "accion": "revision_humana",
            "errores": estado.get("errores", []) + problemas,
            "auditoria": _evento(
                estado,
                "guardar_vacante",
                "revision_humana",
                "La vacante está incompleta: " + "; ".join(problemas),
            ),
        }

    try:
        procesado = modulo_procesar_correo.procesar_correo(
            estado["correo"],
            estado.get("cliente"),
            estado.get("vacante") or None,
        )
    except (ErrorVacante, OSError, ValueError, KeyError) as error:
        _registrar(estado, "error", vacante.get("id", ""))
        return {
            "accion": "error",
            "errores": estado.get("errores", []) + [str(error)],
            "auditoria": _evento(estado, "guardar_vacante", "error", str(error)),
        }

    _registrar(estado, "vacante_guardada", procesado["vacante"]["id"])

    return {
        "accion": "vacante_guardada",
        "resultado": procesado,
        "auditoria": _evento(
            estado,
            "guardar_vacante",
            "vacante_guardada",
            f"Vacante {procesado['vacante']['id']} guardada; shortlist con "
            f"{len(procesado['resultado']['shortlist'])} perfiles.",
        ),
    }


def guardar_candidato_nodo(estado: EstadoCorreo) -> dict:
    """Agrega el perfil a data/candidatos.csv para futuros matchings."""

    from src.candidatos import guardar_candidato

    candidato = estado["datos"]

    try:
        ruta = guardar_candidato(candidato, estado["correo"], "texto libre del correo")
    except OSError as error:
        _registrar(estado, "error")
        return {
            "accion": "error",
            "errores": estado.get("errores", []) + [str(error)],
            "auditoria": _evento(estado, "guardar_candidato", "error", str(error)),
        }

    _registrar(estado, "candidato_guardado", candidato["id"])

    return {
        "accion": "candidato_guardado",
        "resultado": {"candidato": candidato, "ruta_correo": ruta},
        "auditoria": _evento(
            estado,
            "guardar_candidato",
            "candidato_guardado",
            f"Candidato {candidato['id']} ({candidato.get('nombre') or 'sin nombre'}) guardado.",
        ),
    }


def descartar_nodo(estado: EstadoCorreo) -> dict:
    _registrar(estado, "descartado")
    return {
        "accion": "descartado",
        "auditoria": _evento(
            estado,
            "descartar",
            "descartado",
            "El correo no describe ni una vacante ni un candidato.",
        ),
    }


def construir_grafo_correo():
    grafo = StateGraph(EstadoCorreo)
    grafo.add_node("interpretar_correo", interpretar_correo)
    grafo.add_node("guardar_vacante", guardar_vacante_nodo)
    grafo.add_node("guardar_candidato", guardar_candidato_nodo)
    grafo.add_node("descartar", descartar_nodo)

    grafo.add_edge(START, "interpretar_correo")
    grafo.add_conditional_edges(
        "interpretar_correo",
        lambda estado: estado["tipo"],
        {
            TIPO_VACANTE: "guardar_vacante",
            TIPO_CANDIDATO: "guardar_candidato",
            TIPO_DESCONOCIDO: "descartar",
        },
    )
    grafo.add_edge("guardar_vacante", END)
    grafo.add_edge("guardar_candidato", END)
    grafo.add_edge("descartar", END)

    return grafo.compile()


app_correo = construir_grafo_correo()


def interpretar_y_guardar(
    texto: str,
    correo: Correo,
    cliente=None,
    vacante: dict | None = None,
) -> EstadoCorreo:
    """Ejecuta el grafo completo para un correo.

    Si `vacante` viene armada (bandeja simulada), se usa tal cual en vez de
    reconstruirla desde el texto (RF-15).
    """

    estado_inicial: EstadoCorreo = {
        "correo": correo,
        "texto": texto,
        "vacante": vacante or {},
        "tipo": TIPO_DESCONOCIDO,
        "datos": {},
        "pistas": [],
        "advertencias": [],
        "interpretado": None,
        "accion": "",
        "resultado": {},
        "errores": [],
        "auditoria": [],
        "cliente": cliente,
    }
    return app_correo.invoke(estado_inicial)
