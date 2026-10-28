"""Procesamiento de los correos de la bandeja simulada (RF-15).

Se separa del grafo real (`grafo_correo`) porque la corrida de la bandeja
simulada es una simulación: sus candidatos y su catálogo de vacantes viven en
un directorio de trabajo aparte y **no** deben modificar el dataset de `data/`
(eso contaría dos veces al mismo candidato en el siguiente matching).

Reglas de RF-15:

- Solo un correo de vacante dispara el matching.
- Un reenvío de una vacante ya guardada se registra pero no vuelve a correr
  el matching.
- Un correo de gestión o basura no dispara nada.

La clasificación en sí la hace `src.clasificar_correos` (RF-16): vacante
nueva, duplicado de una vacante ya recibida o no relacionado. Aquí solo se
traduce esa decisión a lo que hace el agente con cada correo.
"""

RETRASO_DE_REENVIO = "reenvio"
SIN_VACANTE = "sin_vacante"
VACANTE_GUARDADA = "vacante_guardada"
YA_PROCESADA = "ya_procesada"
REVISION_HUMANA = "revision_humana"


def revisar_correo(correo: dict, vacantes: list[dict]) -> dict:
    """Decide qué hacer con un correo simulado, sin escribir nada.

    Devuelve `accion` (`vacante_guardada`, `ya_procesada`, `reenvio`,
    `revision_humana` o `sin_vacante`) y la vacante cuando corresponde.
    """

    from src.solicitud_vacante import validar_vacante

    vacante = correo.get("vacante_estructurada")
    if not isinstance(vacante, dict) or not vacante.get("id"):
        return {"accion": SIN_VACANTE, "vacante": None, "errores": []}

    problemas = validar_vacante(vacante)
    if problemas:
        return {"accion": REVISION_HUMANA, "vacante": vacante, "errores": problemas}

    existente = next((v for v in vacantes if v.get("id") == vacante["id"]), None)
    if existente is not None:
        if existente == vacante:
            return {"accion": YA_PROCESADA, "vacante": vacante, "errores": []}
        return {"accion": RETRASO_DE_REENVIO, "vacante": vacante, "errores": []}

    return {"accion": VACANTE_GUARDADA, "vacante": vacante, "errores": []}


def vacante_de_texto_libre(texto: str) -> dict | None:
    """Vacante reconstruida del texto libre, solo si el texto describe una.

    En la bandeja simulada un correo sin `vacante_estructurada` que sí
    describe un puesto cuenta como vacante; si no lo describe, no dispara
    el matching.
    """

    from src.interpretar_texto import TIPO_VACANTE, interpretar

    interpretado = interpretar(texto)
    if interpretado.tipo != TIPO_VACANTE:
        return None

    datos = interpretado.datos
    aporta = bool(
        datos.get("skills_obligatorios")
        or datos.get("experience_required") is not None
        or datos.get("english_required")
    )
    return datos if aporta else None


def clasificar_correo(correo: dict) -> dict:
    """Decide qué es el correo antes de tocar el catálogo (RF-15).

    - `vacante`: el texto describe un puesto (o trae `vacante_estructurada`).
    - `candidato`: el texto habla en primera persona de un perfil.
    - `desconocido`: gestión, boletín, factura o texto sin señales.

    Solo `vacante` dispara el matching. Una consulta o un correo de gestión
    que solo habla de "solicitudes de vacante" no es una vacante.
    """

    from src.interpretar_texto import TIPO_CANDIDATO, TIPO_VACANTE, interpretar

    interpretado = interpretar(str(correo.get("cuerpo") or ""))
    vacante = correo.get("vacante_estructurada")
    tiene_estructura = isinstance(vacante, dict) and bool(vacante.get("id"))

    if interpretado.tipo == TIPO_CANDIDATO:
        return {
            "tipo": TIPO_CANDIDATO,
            "vacante": None,
            "datos": interpretado.datos,
            "advertencias": interpretado.advertencias,
        }

    if tiene_estructura:
        return {
            "tipo": TIPO_VACANTE,
            "vacante": vacante,
            "datos": interpretado.datos,
            "advertencias": interpretado.advertencias,
        }

    # Sin vacante armada el texto tiene que aportar datos del puesto; un
    # correo que solo pregunta por el proceso no alcanza.
    datos = interpretado.datos
    aporta = bool(
        datos.get("skills_obligatorios")
        or datos.get("experience_required") is not None
        or datos.get("english_required")
    )
    if interpretado.tipo == TIPO_VACANTE and aporta:
        tipo = TIPO_VACANTE
    else:
        tipo = "desconocido"

    return {
        "tipo": tipo,
        "vacante": None,
        "datos": datos,
        "advertencias": interpretado.advertencias,
    }


def procesar_correo(
    correo: dict,
    vacantes: list[dict],
    estado_simulado: dict,
    cola: dict | None = None,
    modo: str | None = None,
    llm=None,
) -> dict:
    """Procesa un correo simulado contra el estado de la simulación.

    `vacantes` es el catálogo de la simulación (se modifica en sitio) y
    `estado_simulado` acumula los resultados por vacante. La clasificación
    (RF-16) decide qué hacer con el correo: solo `vacante_nueva` entra a la
    cola y dispara el matching; un `duplicado` o un `no_relacionado` se
    registran; lo que no trae rol o skills obligatorios va a revisión humana.

    Si se pasa `cola` (estado de `src.clasificar_correos`), la vacante queda
    en ella y se marca como procesada al terminar el matching.
    """

    from src.clasificar_correos import (
        DUPLICADO,
        NO_RELACIONADO,
        REVISION_HUMANA as REVISION_CLASIFICACION,
        VACANTE_NUEVA,
        encolar,
        guardar_cola,
        marcar_procesada,
    )
    from src.configuracion import cargar_configuracion
    from src.estado_agente import crear_estado_inicial
    from src.ejecutar_matching import invocar_con_limite
    from src.procesar_correo import cargar_candidatos

    base = {
        "message_id": correo.get("message_id", ""),
        "vacante_id": "",
        "shortlist": 0,
        "errores": [],
        "disparo_matching": False,
    }

    cola = cola if cola is not None else {
        "vacantes": [],
        "duplicados": [],
        "revision_humana": [],
    }
    decision = encolar(correo, cola, modo=modo, llm=llm)

    if decision["clase"] == NO_RELACIONADO:
        return {**base, "accion": decision.get("tipo_texto") or NO_RELACIONADO}

    if decision["clase"] == DUPLICADO:
        return {
            **base,
            "accion": DUPLICADO,
            "vacante_id": decision.get("vacante_id", ""),
        }

    if decision["clase"] == REVISION_CLASIFICACION:
        return {
            **base,
            "accion": REVISION_HUMANA,
            "vacante_id": decision.get("vacante_id", ""),
            "errores": decision.get("errores", []),
        }

    if decision["clase"] != VACANTE_NUEVA:
        return {**base, "accion": decision["clase"]}

    # Vacante nueva: ya está en la cola y dispara el matching en este mismo
    # ciclo; al cerrar el matching sale de la cola.
    vacante = decision["vacante"]
    vacantes.append(vacante)
    resultado = invocar_con_limite(
        crear_estado_inicial(vacante, cargar_candidatos()),
        cargar_configuracion(),
    )
    estado_simulado[vacante["id"]] = resultado
    marcar_procesada(cola, vacante["id"])
    guardar_cola(cola)

    return {
        **base,
        "accion": VACANTE_GUARDADA,
        "vacante_id": vacante["id"],
        "shortlist": len(resultado["shortlist"]),
        "disparo_matching": True,
        "clase": decision["clase"],
        "fuente": decision.get("fuente", ""),
    }
