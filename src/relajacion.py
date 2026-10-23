
"""Relajación de criterios cuando la vacante no se completa (RF-06).

Orden de relajación (data/config.yaml -> relaxation.order):

1. Fecha de inicio: se mueve 2 semanas hacia adelante.
2. Experiencia: se acepta 1 año menos.
3. Inglés: se acepta un nivel menos.

Los skills obligatorios **nunca** se relajan. Los criterios relajados son
solo los que la vacante exige: una vacante sin nivel de inglés no acumula
relajaciones de inglés. Cada criterio se relaja una sola vez y en ese orden,
hasta un máximo de `max_relaxations` relajaciones (3 por defecto).
"""

from datetime import date, timedelta

from src.configuracion import Configuracion
from src.scoring import NIVELES_INGLES


SIN_MAS_CRITERIOS = "sin_mas_criterios"


def _fecha(valor) -> date | None:
    try:
        return date.fromisoformat(str(valor or "").strip())
    except ValueError:
        return None


def relajaciones_posibles(
    vacante_original: dict,
    aplicadas: list[dict],
) -> list[dict]:
    """Devuelve las relajaciones que todavía se pueden aplicar, en orden."""

    tipos_aplicados = {relajacion["tipo"] for relajacion in aplicadas}
    posibles = []

    criterios = {
        "start_date": bool(str(vacante_original.get("availability_required") or "").strip()),
        "experience": int(vacante_original.get("experience_required") or 0) > 0,
        "english": str(vacante_original.get("english_required") or "").strip().upper()
        in NIVELES_INGLES,
    }

    for paso in ("start_date", "experience", "english"):
        if criterios[paso] and paso not in tipos_aplicados:
            posibles.append({"tipo": paso})

    return posibles


def aplicar_relajacion(
    vacante_anterior: dict,
    aplicadas: list[dict],
    config: Configuracion,
) -> tuple[dict, dict | None, str]:
    """Aplica la siguiente relajación de la secuencia.

    Devuelve (vacante_nueva, relajacion_aplicada, estado):
    - `relajacion` es None si ya no quedan criterios por relajar.
    - `estado` vale "aplicada", "agotada" (llego al máximo) o
      SIN_MAS_CRITERIOS.
    """

    if len(aplicadas) >= config.max_relajaciones:
        return vacante_anterior, None, "agotada"

    posibles = relajaciones_posibles(vacante_anterior, aplicadas)
    if not posibles:
        return vacante_anterior, None, SIN_MAS_CRITERIOS

    tipo = posibles[0]["tipo"]
    vacante_nueva = dict(vacante_anterior)

    if tipo == "start_date":
        fecha = _fecha(vacante_anterior.get("availability_required"))
        vacante_nueva["availability_required"] = (fecha + timedelta(weeks=2)).isoformat()
        relajacion = {
            "tipo": tipo,
            "antes": fecha.isoformat(),
            "despues": vacante_nueva["availability_required"],
            "descripcion": (
                "Se movió la fecha de inicio 2 semanas: "
                f"{fecha.isoformat()} -> {vacante_nueva['availability_required']}."
            ),
        }
    elif tipo == "experience":
        antes = int(vacante_anterior.get("experience_required") or 0)
        vacante_nueva["experience_required"] = max(0, antes - 1)
        relajacion = {
            "tipo": tipo,
            "antes": antes,
            "despues": vacante_nueva["experience_required"],
            "descripcion": (
                "Se acepta 1 año menos de experiencia: "
                f"{antes} -> {vacante_nueva['experience_required']} años."
            ),
        }
    else:
        antes = str(vacante_anterior.get("english_required")).strip().upper()
        indice = max(0, NIVELES_INGLES.index(antes) - 1)
        vacante_nueva["english_required"] = NIVELES_INGLES[indice]
        relajacion = {
            "tipo": tipo,
            "antes": antes,
            "despues": vacante_nueva["english_required"],
            "descripcion": (
                "Se acepta un nivel menos de inglés: "
                f"{antes} -> {vacante_nueva['english_required']}."
            ),
        }

    return vacante_nueva, relajacion, "aplicada"
