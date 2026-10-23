
"""Puntuación determinista de candidatos y justificaciones por plantilla.

No usa LLM: la vacante ya llega estructurada y cada justificación se arma
con una plantilla a partir de los datos calculados (RNF-02).
Con el mismo dataset y configuración, el puntaje es siempre el mismo (RNF-03).
"""

from datetime import date

from src.configuracion import Configuracion
from src.duplicados import normalizar_texto


NIVELES_INGLES = ("A1", "A2", "B1", "B2", "C1", "C2")


def nivel_ingles_valor(nivel) -> int:
    """Convierte un nivel MCER (A1..C2) en número para poder compararlo."""

    nivel = str(nivel or "").strip().upper()
    if nivel not in NIVELES_INGLES:
        return -1

    return NIVELES_INGLES.index(nivel) + 1


def _skills(candidato: dict) -> list[str]:
    """Skills del candidato tal como vienen en el dataset (sin normalizar)."""

    texto = candidato.get("skills") or ""
    return [skill.strip() for skill in str(texto).split(";") if skill.strip()]


def _normalizar_skills(valores) -> list[str]:
    """Skills de la vacante tal como vienen en el JSON (sin normalizar)."""

    return [str(valor).strip() for valor in (valores or []) if str(valor).strip()]


def _contiene(skills: list[str], skill: str) -> bool:
    buscado = normalizar_texto(skill)
    return any(normalizar_texto(actual) == buscado for actual in skills)


def _modalidad_compatible(modalidad_candidato: str, modalidad_vacante: str) -> bool:
    """Remoto del candidato sirve para cualquier vacante; híbrido cubre presencial."""

    candidato = normalizar_texto(modalidad_candidato)
    vacante = normalizar_texto(modalidad_vacante)

    if candidato == vacante:
        return True
    if candidato == "remoto":
        return True
    if candidato == "hibrido" and vacante == "presencial":
        return True

    return False


def evaluar_candidato(candidato: dict, vacante: dict, config: Configuracion) -> dict:
    """Calcula los criterios, el puntaje (0-100) y los motivos plantilla."""

    pesos = config.pesos
    skills_candidato = _skills(candidato)
    obligatorios = _normalizar_skills(vacante.get("skills_obligatorios"))
    deseables = _normalizar_skills(vacante.get("skills_deseables"))

    cumplidos = [s for s in obligatorios if _contiene(skills_candidato, s)]
    faltantes = [s for s in obligatorios if _contiene(cumplidos, s) is False]
    deseables_cumplidos = [s for s in deseables if _contiene(skills_candidato, s)]

    skill_score = (
        pesos["mandatory_skills"] * len(cumplidos) / len(obligatorios)
        if obligatorios
        else pesos["mandatory_skills"]
    )
    deseable_score = (
        pesos["desirable_skills"] * len(deseables_cumplidos) / len(deseables)
        if deseables
        else pesos["desirable_skills"]
    )

    try:
        experiencia = int(candidato.get("experience_years"))
    except (TypeError, ValueError):
        experiencia = 0

    requerida = int(vacante.get("experience_required") or 0)
    cumple_experiencia = experiencia >= requerida
    # 15 si cumple los años; 8 si le falta 1 año; 0 si le faltan más.
    if requerida == 0 or experiencia >= requerida:
        experience_score = pesos["experience"]
    elif experiencia == requerida - 1:
        experience_score = pesos["experience"] / 2
    else:
        experience_score = 0.0

    nivel_candidato = nivel_ingles_valor(candidato.get("english_level"))
    nivel_requerido = nivel_ingles_valor(vacante.get("english_required"))
    cumple_ingles = nivel_candidato >= nivel_requerido
    # 10 si cumple el nivel; 5 si está un nivel abajo; 0 si está más abajo.
    if cumple_ingles:
        english_score = pesos["english"]
    elif nivel_requerido > 0 and nivel_candidato == nivel_requerido - 1:
        english_score = pesos["english"] / 2
    else:
        english_score = 0.0

    fecha_candidato = str(candidato.get("availability_date") or "").strip()
    fecha_requerida = str(vacante.get("availability_required") or "").strip()
    cumple_fecha = None

    if fecha_requerida and fecha_candidato:
        try:
            cumple_fecha = date.fromisoformat(fecha_candidato) <= date.fromisoformat(fecha_requerida)
        except ValueError:
            cumple_fecha = None

    cumple_modalidad = _modalidad_compatible(
        candidato.get("modality", ""),
        vacante.get("modality", ""),
    )

    availability_score = (
        pesos["availability"] if cumple_fecha and cumple_modalidad else 0.0
    )

    puntaje = round(
        skill_score + deseable_score + experience_score + english_score + availability_score,
        2,
    )

    encontrados = {
        "skills_candidato": skills_candidato,
        "obligatorios": obligatorios,
        "cumplidos": cumplidos,
        "faltantes": faltantes,
        "deseables_cumplidos": deseables_cumplidos,
        "experiencia": experiencia,
        "experiencia_requerida": requerida,
        "nivel_candidato": str(candidato.get("english_level") or "").strip().upper(),
        "nivel_requerido": str(vacante.get("english_required") or "").strip().upper(),
        "nivel_candidato_valor": nivel_candidato,
        "nivel_requerido_valor": nivel_requerido,
        "fecha_candidato": fecha_candidato,
        "fecha_requerida": fecha_requerida,
        "a_tiempo": cumple_fecha is True,
        "modalidad_candidato": candidato.get("modality", ""),
        "modalidad_vacante": vacante.get("modality", ""),
        "modalidad_ok": cumple_modalidad,
    }

    criterios = {
        "mandatory_skills": round(skill_score, 2),
        "desirable_skills": round(deseable_score, 2),
        "experience": round(experience_score, 2),
        "english": round(english_score, 2),
        "availability": round(availability_score, 2),
    }

    cumple_requisitos = (
        not faltantes
        and cumple_experiencia
        and cumple_ingles
        and cumple_fecha is True
        and cumple_modalidad
    )

    return {
        "puntaje": puntaje,
        "criterios": criterios,
        "cumple_requisitos": cumple_requisitos,
        "motivo": construir_justificacion(candidato, encontrados, cumple_requisitos),
        "detalle": encontrados,
    }


def construir_justificacion(candidato: dict, datos: dict, cumple_requisitos: bool) -> str:
    """Arma la justificación con una plantilla fija (sin LLM)."""

    total = len(datos["obligatorios"])
    if datos["cumplidos"]:
        skills = f"{len(datos['cumplidos'])}/{total} skills obligatorios ({', '.join(datos['cumplidos'])})"
    else:
        skills = f"0/{total} skills obligatorios"

    if datos["faltantes"]:
        skills += f" (faltan: {', '.join(datos['faltantes'])})"

    deseables = (
        ", ".join(datos["deseables_cumplidos"]) if datos["deseables_cumplidos"] else "ninguno"
    )

    experiencia = (
        f"{datos['experiencia']} años (requiere {datos['experiencia_requerida']})"
    )

    ingles = (
        f"{datos['nivel_candidato'] or 'sin dato'} "
        f"(requiere {datos['nivel_requerido']})"
    )

    if datos["fecha_candidato"] and datos["fecha_requerida"]:
        try:
            a_tiempo = date.fromisoformat(datos["fecha_candidato"]) <= date.fromisoformat(
                datos["fecha_requerida"]
            )
        except ValueError:
            a_tiempo = False
        disponibilidad = (
            f"disponible desde {datos['fecha_candidato']} "
            f"({'a tiempo' if a_tiempo else 'después de lo requerido'}, "
            f"se requiere para {datos['fecha_requerida']})"
        )
    elif datos["fecha_candidato"]:
        disponibilidad = f"disponible desde {datos['fecha_candidato']}"
    else:
        disponibilidad = "sin fecha de disponibilidad (dato faltante)"

    modalidad = (
        f"modalidad {datos['modalidad_candidato'] or 'sin dato'} "
        f"(vacante {datos['modalidad_vacante'] or 'sin dato'})"
    )

    pendientes = []
    if datos["faltantes"]:
        pendientes.append(f"faltan skills obligatorios ({', '.join(datos['faltantes'])})")
    if datos["experiencia"] < datos["experiencia_requerida"]:
        faltan = datos["experiencia_requerida"] - datos["experiencia"]
        pendientes.append(
            f"experiencia insuficiente ({datos['experiencia']} de "
            f"{datos['experiencia_requerida']} años, faltan {faltan})"
        )
    if datos["nivel_candidato_valor"] < datos["nivel_requerido_valor"]:
        pendientes.append(
            f"inglés {datos['nivel_candidato'] or 'sin dato'} por debajo de "
            f"{datos['nivel_requerido']}"
        )
    if datos["fecha_candidato"] and datos["fecha_requerida"] and not datos["a_tiempo"]:
        pendientes.append("no disponible para la fecha requerida")
    if not datos["fecha_candidato"]:
        pendientes.append("disponibilidad sin confirmar")
    if not datos["modalidad_ok"]:
        pendientes.append(f"modalidad {datos['modalidad_candidato']} no compatible")

    if cumple_requisitos:
        veredicto = "Cumple todos los requisitos obligatorios."
    elif pendientes:
        veredicto = f"No cumple todos los requisitos obligatorios: {'; '.join(pendientes)}."
    else:
        veredicto = "No cumple todos los requisitos obligatorios."

    return (
        f"{candidato.get('nombre', candidato.get('id', 'Candidato'))}: {veredicto} "
        f"Skills: {skills}. Deseables: {deseables}. Experiencia: {experiencia}. "
        f"Inglés: {ingles}. Disponibilidad: {disponibilidad}. Modalidad: {modalidad}."
    )



def construir_shortlist(
    candidatos: list[dict],
    vacante: dict,
    config: Configuracion,
) -> list[dict]:
    """Evalúa candidatos y devuelve únicamente los aptos que superan el umbral."""

    calificados = [
        {
            "id": candidato.get("id", ""),
            **evaluar_candidato(candidato, vacante, config),
        }
        for candidato in candidatos
    ]

    # Orden estable: mayor puntaje primero y, en empate, ID ascendente.
    calificados.sort(key=lambda item: (-item["puntaje"], item["id"]))

    # Un candidato debe cumplir todos los requisitos obligatorios
    # y alcanzar el umbral mínimo de puntuación.
    aptos = [
        item
        for item in calificados
        if item["cumple_requisitos"]
        and item["puntaje"] >= config.threshold
    ]

    shortlist = aptos[: config.shortlist_size]

    return [
        {
            "posicion": posicion,
            **item,
            "justificacion": item["motivo"],
            "supera_umbral": item["puntaje"] >= config.threshold,
        }
        for posicion, item in enumerate(shortlist, start=1)
    ]



MINIMO_APTOS = 3


def evaluar_resultado(
    calificados: list[dict],
    config: Configuracion,
    minimo: int = MINIMO_APTOS,
) -> dict:
    """Evalúa si la vacante tuvo éxito (RF-05).

    Hay éxito si al menos `minimo` candidatos (3 por defecto) superan el
    umbral. La condición se evalúa sobre la shortlist vigente: cualquier
    candidato con puntaje mayor o igual al umbral que todavía no tiene
    un puesto asignado.
    """

    aptos = [item for item in calificados if item["puntaje"] >= config.threshold]
    cubiertos = [item for item in calificados if item.get("posicion")]

    return {
        "exito": len(aptos) >= minimo,
        "aptos": len(aptos),
        "minimo": minimo,
        "cubiertos": len(cubiertos),
        "puestos_libres": max(0, config.shortlist_size - len(cubiertos)),
        "umbral": config.threshold,
    }
