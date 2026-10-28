
"""Convierte un correo con solicitud de vacante en una vacante estructurada.

El agente de matching trabaja con vacantes ya normalizadas (RF-01), así que
aquí se extrae el JSON del cuerpo o del adjunto .json y se valida contra el
mismo esquema de `data/vacantes.json`. No usa LLM: si el correo no trae la
vacante estructurada se informa el problema en vez de inventar datos (RNF-03).
"""

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import date

from src.agentmail_cliente import Adjunto, Correo


NIVELES_INGLES = {"A1", "A2", "B1", "B2", "C1", "C2"}
MODALIDADES = {"remoto", "hibrido", "presencial"}

CAMPOS_OBLIGATORIOS = {
    "titulo",
    "skills_obligatorios",
    "skills_deseables",
    "experience_required",
    "english_required",
    "availability_required",
    "modality",
}


class ErrorVacante(ValueError):
    """El correo no contiene una vacante con el formato esperado."""


@dataclass
class SolicitudVacante:
    """Vacante extraída de un correo, junto con su trazabilidad."""

    vacante: dict
    origen: str
    correo: Correo
    advertencias: list[str] = field(default_factory=list)


def validar_vacante(datos: dict) -> list[str]:
    """Devuelve la lista de problemas de una vacante; vacía si es válida."""

    errores = []

    if not isinstance(datos, dict):
        return ["La vacante debe ser un objeto JSON."]

    faltantes = CAMPOS_OBLIGATORIOS - set(datos)
    if faltantes:
        errores.append(f"faltan campos {sorted(faltantes)}")

    identificador = datos.get("id") or "(sin ID)"

    if not str(datos.get("titulo") or "").strip():
        errores.append(f"{identificador}: falta título")

    for campo in ("skills_obligatorios", "skills_deseables"):
        skills = datos.get(campo)
        if not isinstance(skills, list) or any(
            not isinstance(skill, str) or not skill.strip() for skill in skills
        ):
            errores.append(f"{identificador}: {campo} no tiene formato válido")

    try:
        if int(datos.get("experience_required")) < 0:
            errores.append(f"{identificador}: experiencia requerida negativa")
    except (TypeError, ValueError):
        errores.append(f"{identificador}: experiencia requerida no válida")

    if datos.get("english_required") not in NIVELES_INGLES:
        errores.append(f"{identificador}: nivel de inglés requerido no válido")

    if datos.get("modality") not in MODALIDADES:
        errores.append(f"{identificador}: modalidad no válida")

    try:
        date.fromisoformat(str(datos.get("availability_required")))
    except (TypeError, ValueError):
        errores.append(f"{identificador}: fecha requerida no válida")

    return errores


def _candidatos_json(texto: str) -> list[dict]:
    """Extrae objetos JSON de un texto: el completo o el bloque {...} que haya."""

    texto = (texto or "").strip()
    if not texto:
        return []

    try:
        return [json.loads(texto)]
    except ValueError:
        pass

    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fin <= inicio:
        return []

    try:
        return [json.loads(texto[inicio : fin + 1])]
    except ValueError:
        return []


def _vacante_desde_json(json_datos) -> dict | None:
    """Acepta un objeto vacante, una lista o un contenedor {"vacantes": [...]}."""

    if isinstance(json_datos, list):
        for elemento in json_datos:
            vacante = _vacante_desde_json(elemento)
            if vacante:
                return vacante
        return None

    if not isinstance(json_datos, dict):
        return None

    if isinstance(json_datos.get("vacantes"), list):
        return _vacante_desde_json(json_datos["vacantes"])

    if isinstance(json_datos.get("vacante"), dict):
        return _vacante_desde_json(json_datos["vacante"])

    if CAMPOS_OBLIGATORIOS & set(json_datos):
        return json_datos

    return None


def _desde_csv(contenido: bytes) -> dict | None:
    """Convierte una fila CSV con las columnas de la vacante en un objeto."""

    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = contenido.decode("latin-1")

    filas = list(csv.DictReader(io.StringIO(texto)))
    if not filas:
        return None

    fila = filas[0]
    vacante = {"id": (fila.get("id") or "").strip(), "titulo": (fila.get("titulo") or "").strip()}

    for campo in ("skills_obligatorios", "skills_deseables"):
        vacante[campo] = [
            skill.strip() for skill in (fila.get(campo) or "").split(";") if skill.strip()
        ]

    for campo in ("experience_required", "availability_required", "english_required", "modality"):
        vacante[campo] = (fila.get(campo) or "").strip()

    if "experience_required" in vacante:
        try:
            vacante["experience_required"] = int(vacante["experience_required"])
        except ValueError:
            pass

    return vacante if CAMPOS_OBLIGATORIOS & set(vacante) else None


def extraer_vacante(
    correo: Correo,
    descargar_adjunto=None,
    vacante_estructurada: dict | None = None,
) -> SolicitudVacante:
    """Busca la vacante en el cuerpo del correo y, si falla, en sus adjuntos.

    En la bandeja simulada la vacante ya viene armada (`vacante_estructurada`)
    y tiene prioridad sobre el texto, así un correo reenviado guarda la misma
    vacante y no una reconstruida (RF-15).

    `descargar_adjunto` es una función (message_id, attachment_id) -> bytes;
    se pasa como argumento para poder probar sin red.
    """

    advertencias = []
    problemas = []

    if isinstance(vacante_estructurada, dict):
        vacante = vacante_estructurada
    else:
        vacante = None

    for datos in ([] if vacante else _candidatos_json(correo.cuerpo)):
        vacante = _vacante_desde_json(datos)
        if vacante is None:
            continue
        problemas = validar_vacante(vacante)
        if not problemas:
            return SolicitudVacante(vacante, "cuerpo del correo", correo, advertencias)
        raise ErrorVacante(
            f"La vacante del cuerpo del correo no es válida: {'; '.join(problemas)}"
        )

    if vacante is not None:
        problemas = validar_vacante(vacante)
        if problemas:
            raise ErrorVacante(
                "La vacante estructurada del correo no es válida: " + "; ".join(problemas)
            )
        return SolicitudVacante(
            vacante, "vacante estructurada de la bandeja simulada", correo, advertencias
        )

    for adjunto in correo.adjuntos:
        if not _es_adjunto_candidato(descargar_adjunto, correo, adjunto, advertencias):
            continue

        contenido = descargar_adjunto(correo.message_id, adjunto.attachment_id)

        if adjunto.filename.lower().endswith(".json"):
            vacante = _vacante_desde_json(
                _candidatos_json(contenido.decode("utf-8-sig", errors="replace"))
            )
        else:
            vacante = _desde_csv(contenido)

        if vacante is None:
            advertencias.append(f"{adjunto.filename}: no contiene una vacante reconocible.")
            continue

        problemas = validar_vacante(vacante)
        if problemas:
            raise ErrorVacante(
                f"La vacante del adjunto {adjunto.filename} no es válida: "
                f"{'; '.join(problemas)}"
            )

        return SolicitudVacante(vacante, f"adjunto {adjunto.filename}", correo, advertencias)

    detalle = "; ".join(problemas + advertencias) or (
        "no se encontró un JSON de vacante (skills_obligatorios) ni un adjunto .json/.csv"
    )
    raise ErrorVacante(f"No se pudo extraer la vacante: {detalle}")


def _es_adjunto_candidato(descargar_adjunto, correo, adjunto: Adjunto, advertencias) -> bool:
    """Solo se descargan adjuntos que puedan ser vacantes."""

    nombre = (adjunto.filename or "").lower()
    if not nombre.endswith((".json", ".csv")):
        return False
    if not adjunto.attachment_id:
        advertencias.append(f"{adjunto.filename}: adjunto sin identificador.")
        return False
    if descargar_adjunto is None:
        advertencias.append(f"{adjunto.filename}: no se proporcionó descarga de adjuntos.")
        return False
    return True
