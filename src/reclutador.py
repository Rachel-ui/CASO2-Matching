
"""Consulta del dato faltante al reclutador simulado (RF-04).

Cuando un candidato no trae la fecha de disponibilidad, el agente no
inventa el dato: pregunta al reclutador simulado (data/reclutador.json) y
usa la respuesta. Si la respuesta es "no se sabe" o no existe, el campo
queda vacío y la disponibilidad se puntúa con 0 (no se cumple).

Cada pregunta queda registrada junto con su respuesta en
`consultas_reclutador` para que aparezca en el log de auditoría.
"""

import json
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
ARCHIVO_RECLUTADOR = RAIZ / "data" / "reclutador.json"

CAMPO_DISPONIBILIDAD = "availability_date"
RESPUESTA_SIN_DATO = "no se sabe"


def cargar_respuestas(ruta: Path | None = None) -> list[dict]:
    """Lee las respuestas del reclutador simulado."""

    ruta = Path(ruta) if ruta else ARCHIVO_RECLUTADOR

    with ruta.open("r", encoding="utf-8-sig") as archivo:
        return json.load(archivo).get("consultas", [])


def buscar_respuesta(candidato_id: str, campo: str, respuestas: list[dict]) -> str:
    """Devuelve la respuesta del reclutador para ese candidato y campo."""

    for consulta in respuestas:
        if (
            consulta.get("candidate_id") == candidato_id
            and consulta.get("campo") == campo
        ):
            return str(consulta.get("respuesta", "")).strip()

    return ""


def datos_faltantes(candidato: dict) -> list[str]:
    """Campos que el candidato no trae y que el reclutador puede saber."""

    if not str(candidato.get(CAMPO_DISPONIBILIDAD) or "").strip():
        return [CAMPO_DISPONIBILIDAD]

    return []


def consultar_candidato(
    candidato: dict,
    respuestas: list[dict],
) -> tuple[dict, list[dict]]:
    """Pregunta al reclutador por los datos faltantes del candidato.

    Devuelve (candidato_actualizado, consultas). El candidato original no
    se modifica. Las respuestas que no son fechas o son "no se sabe" dejan
    el campo vacío y se registran como no respondidas.
    """

    identificador = candidato.get("id", "")

    consultas = [
        _preparar(respuestas, identificador, campo)
        for campo in datos_faltantes(candidato)
    ]

    return _candidato_actualizado(candidato, consultas), consultas


def _preparar(respuestas: list[dict], identificador: str, campo: str) -> dict:
    """Arma la pregunta y la respuesta del reclutador para un campo."""

    respuesta = buscar_respuesta(identificador, campo, respuestas)

    if not respuesta:
        resultado = "sin_respuesta"
        motivo = "El reclutador no tiene una respuesta registrada para este dato."
    elif respuesta.lower().startswith(RESPUESTA_SIN_DATO):
        resultado = "no_se_sabe"
        motivo = 'El reclutador respondió "no se sabe"; el dato sigue desconocido.'
    else:
        resultado = "respondida"
        motivo = f"El reclutador confirmó {campo} = {respuesta}."

    return {
        "candidato_id": identificador,
        "campo": campo,
        "pregunta": f"¿Cuál es la {campo} del candidato {identificador}?",
        "respuesta": respuesta,
        "resultado": resultado,
        "motivo": motivo,
    }


def _candidato_actualizado(
    candidato: dict,
    consultas: list[dict],
) -> dict:
    """Aplica al perfil solo las respuestas que tienen un valor utilizable."""

    actualizado = dict(candidato)
    for consulta in consultas:
        if consulta["resultado"] == "respondida" and consulta["respuesta"]:
            actualizado[consulta["campo"]] = consulta["respuesta"]
    return actualizado
