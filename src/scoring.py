
"""Puntuación determinista de candidatos y justificaciones por plantilla.

No usa LLM: la vacante ya llega estructurada y cada justificación se arma
con una plantilla a partir de los datos calculados (RNF-02).
Con el mismo dataset y configuración, el puntaje es siempre el mismo (RNF-03).
"""

from datetime import date

from src.configuracion import Configuracion
from src.duplicados import normalizar_texto
from src.interpretar_texto import EQUIVALENCIAS_SKILLS


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
    """Si el perfil tiene la skill; "RPG ILE" también cubre "RPG IV"."""

    buscadas = EQUIVALENCIAS_SKILLS.get(skill, (skill,))
    buscadas = {normalizar_texto(buscada) for buscada in buscadas}
    return any(normalizar_texto(actual) in buscadas for actual in skills)


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
# Un perfil entra en "cercanos al umbral" si le faltan como máximo estos
# puntos para que se expliquen los requisitos que lo dejaron fuera (RF-07).
MARGEN_CERCA = 10
# Si nadie queda cerca, se explican como máximo estos mejores perfiles.
MAX_CERCANOS = 5
DESCRIPCIONES = {
    "skills_obligatorios": (
        "Los skills obligatorios: ningún perfil cercano tiene todos los que pide "
        "la vacante y estos no se relajan nunca, así que el puesto no se puede "
        "cubrir ni después de las relajaciones."
    ),
    "experiencia": (
        "La experiencia mínima: incluso tras aceptar un año menos, hay perfiles "
        "cercanos al umbral que no llegan a los años exigidos."
    ),
    "ingles": (
        "El nivel de inglés: incluso tras aceptar un nivel menos, hay perfiles "
        "cercanos al umbral que quedan por debajo."
    ),
    "disponibilidad": (
        "La fecha de disponibilidad: los perfiles cercanos no están disponibles "
        "para la fecha de inicio (ni desplazada 2 semanas), o no tienen el dato "
        "porque se agotaron las consultas al reclutador."
    ),
    "modalidad": (
        "La modalidad: los perfiles cercanos no tienen una modalidad compatible "
        "con la de la vacante y eso no se relaja."
    ),
    "umbral": (
        "La puntuación: los perfiles cercanos cumplen los requisitos duros, pero "
        "no alcanzan el umbral con las relajaciones aplicadas."
    ),
}


def evaluar_resultado(
    calificados: list[dict],
    config: Configuracion,
    minimo: int = MINIMO_APTOS,
) -> dict:
    """Evalúa si la vacante tuvo éxito (RF-05).

    Hay éxito si al menos `minimo` candidatos (3 por defecto) superan el
    umbral. La condición se evalúa sobre la shortlist vigente: cualquier
    candidato con puntaje mayor o igual al umbral que todavía no tiene
    un puesto asignado. Para exigir además 3 puestos cubiertos se usa
    `ajustar_a_shortlist` (RF-05/RF-07).
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


def ajustar_a_shortlist(evaluacion: dict, shortlist: list[dict], size: int) -> dict:
    """Completa la evaluación con los puestos que la shortlist deja cubiertos.

    `aptos` siguen siendo los que superan el umbral (RF-05); `cubiertos` y
    `puestos_libres` dicen si además están cubiertos los puestos. Si no,
    la corrida termina en `exito_parcial` y se relaja (RF-06/RF-07).
    """

    cubiertos = len(shortlist)

    return {
        **evaluacion,
        "cubiertos": cubiertos,
        "puestos_libres": max(0, size - cubiertos),
    }


def explicar_shortlist_incompleta(
    calificados: list[dict],
    vacante: dict,
    shortlist: list[dict],
    config: Configuracion,
) -> dict:
    """Explica qué requisito impide completar la shortlist (RF-07).

    Se toma como base a los candidatos que están en el umbral o a menos de
    10 puntos de él: son los que "casi" entran y por eso explican el bloqueo.
    Para cada requisito duro se cuenta cuántos de ellos lo incumplen, se
    nombran los casos concretos y se marca el requisito que bloquea más
    puestos. Los skills obligatorios nunca se relajan, así que un perfil sin
    todos esos skills no puede entrar a la shortlist ni con 3 relajaciones.
    """

    umbral = config.threshold
    cercanos_a = umbral - MARGEN_CERCA
    posiciones = {item["id"] for item in shortlist}
    cercanos = [
        item
        for item in calificados
        if item["id"] not in posiciones
        and item["puntaje"] >= cercanos_a
    ]

    # Si nadie está cerca del umbral (vacante muy difícil), se explican los
    # mejores perfiles fuera de la shortlist, que son los que casi entran.
    ampliado = not cercanos and bool(calificados)
    if ampliado:
        cercanos = [
            item for item in calificados if item["id"] not in posiciones
        ][:MAX_CERCANOS]

    bloques = {
        "skills_obligatorios": [],
        "experiencia": [],
        "ingles": [],
        "disponibilidad": [],
        "modalidad": [],
        "umbral": [],
    }

    for item in cercanos:
        detalle = item["detalle"]
        etiqueta = f"{item['id']} ({item['puntaje']:g} pts)"

        if detalle["faltantes"]:
            bloques["skills_obligatorios"].append(
                f"{etiqueta}: le faltan {', '.join(detalle['faltantes'])}"
            )
        if detalle["experiencia"] < detalle["experiencia_requerida"]:
            bloques["experiencia"].append(
                f"{etiqueta}: {detalle['experiencia']} de "
                f"{detalle['experiencia_requerida']} años"
            )
        if detalle["nivel_candidato_valor"] < detalle["nivel_requerido_valor"]:
            bloques["ingles"].append(
                f"{etiqueta}: {detalle['nivel_candidato'] or 'sin nivel'} "
                f"frente a {detalle['nivel_requerido']}"
            )
        if not detalle["fecha_candidato"]:
            bloques["disponibilidad"].append(f"{etiqueta}: sin fecha de disponibilidad")
        elif not detalle["a_tiempo"]:
            bloques["disponibilidad"].append(
                f"{etiqueta}: disponible el {detalle['fecha_candidato']}, "
                f"se requiere para el {detalle['fecha_requerida']}"
            )
        if not detalle["modalidad_ok"]:
            bloques["modalidad"].append(
                f"{etiqueta}: modalidad {detalle['modalidad_candidato'] or 'sin dato'}"
            )
        if item["cumple_requisitos"] and item["puntaje"] < umbral:
            bloques["umbral"].append(
                f"{etiqueta}: cumple los requisitos pero está {umbral - item['puntaje']:g} "
                f"puntos bajo el umbral {umbral:g}"
            )

    puestos_libres = max(0, config.shortlist_size - len(shortlist))
    bloqueantes = [
        {"requisito": nombre, "casos": casos}
        for nombre, casos in bloques.items()
        if casos
    ]
    # El primer requisito con más casos es el que más impide completar la
    # shortlist; el orden ya refleja skills -> experiencia -> inglés ->
    # disponibilidad -> modalidad -> umbral.
    bloqueantes.sort(key=lambda bloque: -len(bloque["casos"]))
    principal = bloqueantes[0] if bloqueantes else None

    if not calificados:
        motivo = "No hay perfiles únicos que evaluar."
    elif principal is None:
        motivo = (
            f"No se identificó un requisito bloqueante entre los {len(cercanos)} "
            "perfiles cercanos al umbral."
        )
    elif ampliado:
        motivo = (
            f"Ningún perfil se acerca al umbral {umbral:g}; se explican los "
            f"{len(cercanos)} mejores: {DESCRIPCIONES[principal['requisito']]}"
        )
    else:
        motivo = DESCRIPCIONES[principal["requisito"]]

    return {
        "puestos_libres": puestos_libres,
        "puestos_llenos": len(shortlist),
        "candidatos_en_shortlist": [item["id"] for item in shortlist],
        "perfiles_cercanos": len(cercanos),
        "requisito_principal": principal["requisito"] if principal else "",
        "motivo_principal": motivo,
        "bloqueantes": bloqueantes,
    }
