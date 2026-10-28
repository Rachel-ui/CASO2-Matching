
from langgraph.graph import StateGraph, START, END

from src.configuracion import Configuracion, cargar_configuracion
from src.duplicados import depurar_duplicados
from src.estado_agente import EstadoAgente
from src.reclutador import (
    _candidato_actualizado,
    cargar_respuestas,
    consultar_candidato,
)
from src.relajacion import aplicar_relajacion
from src.scoring import (
    ajustar_a_shortlist,
    construir_shortlist,
    evaluar_candidato,
    evaluar_resultado,
    explicar_shortlist_incompleta,
)


def registrar_auditoria(
    estado: EstadoAgente,
    nodo: str,
    decision: str,
    motivo: str,
    iteracion: int | None = None,
) -> list[dict]:
    """Agrega un evento al log de auditoría (RF-10).

    Cada evento contiene siempre: iteración, nodo, decisión y motivo.
    """

    if iteracion is None:
        iteracion = estado["iteracion"]

    evento = {
        "iteracion": iteracion,
        "nodo": nodo,
        "decision": decision,
        "motivo": motivo,
    }

    return estado["auditoria"] + [evento]


def contar_paso(estado: EstadoAgente) -> dict:
    """Suma un paso del grafo a `pasos_grafo` (RNF-04)."""

    return {"pasos_grafo": 1}


def _contando_pasos(nodo, paso_actual):
    """Envuelve un nodo para que sume un paso del grafo (RNF-04)."""

    def envuelto(estado: EstadoAgente) -> dict:
        resultado = nodo(estado)
        # Cada ejecución del nodo aporta un paso al contador sumable.
        return {**(resultado or {}), **paso_actual(estado)}

    return envuelto


def validar_estado(estado: EstadoAgente) -> dict:
    """Comprueba la vacante, los candidatos y la configuración (RNF-02)."""

    errores = []

    if not estado["vacante_actual"]:
        errores.append("No se recibió una vacante para procesar.")

    if not isinstance(estado["candidatos"], list):
        errores.append("La lista de candidatos no tiene un formato válido.")

    if errores:
        return {
            "errores": estado["errores"] + errores,
            "estado": "error",
            "auditoria": registrar_auditoria(
                estado,
                nodo="validar_estado",
                decision="error",
                motivo="; ".join(errores),
            ),
        }

    try:
        config = cargar_configuracion()
    except (OSError, ValueError) as error:
        return {
            "errores": estado["errores"] + [f"Configuración inválida: {error}"],
            "estado": "error",
            "auditoria": registrar_auditoria(
                estado,
                nodo="validar_estado",
                decision="error",
                motivo=f"Configuración inválida: {error}",
            ),
        }

    modo = "sin LLM" if config.sin_llm else "con LLM"
    auditoria = registrar_auditoria(
        estado,
        nodo="validar_estado",
        decision="continuar",
        motivo=(
            f"Vacante '{estado['vacante_actual'].get('id', 'sin ID')}' válida y "
            f"{len(estado['candidatos'])} candidatos disponibles."
        ),
    )
    auditoria = registrar_auditoria(
        {**estado, "auditoria": auditoria},
        nodo="validar_estado",
        decision=config.modo,
        motivo=(
            f"Modo {modo} activo ({config.modo}); umbral {config.threshold:g}, "
            f"shortlist de {config.shortlist_size} perfiles."
        ),
    )

    return {
        "estado": "datos_validados",
        "indice_candidato": 0,
        "configuracion": config,
        "limites": {**config.limites(), "recursion_limit": config.recursion_limit},
        "auditoria": auditoria,
    }


def depurar_duplicados_nodo(estado: EstadoAgente) -> dict:
    """Detecta perfiles duplicados y deja solo uno por persona (RF-09)."""

    validos, duplicados = depurar_duplicados(estado["candidatos"])

    auditoria = estado["auditoria"]

    if not duplicados:
        auditoria = registrar_auditoria(
            {**estado, "auditoria": auditoria},
            nodo="depurar_duplicados",
            decision="sin_duplicados",
            motivo=f"Los {len(validos)} perfiles son únicos.",
        )
    else:
        for duplicado in duplicados:
            auditoria = registrar_auditoria(
                {**estado, "auditoria": auditoria},
                nodo="depurar_duplicados",
                decision="descartar_duplicado",
                motivo=(
                    f"{duplicado['id']} ({duplicado['nombre']}) se descarta por: "
                    f"{duplicado['motivo']} con el perfil único "
                    f"{duplicado['conservado_id']} (posición {duplicado['posicion']})."
                ),
            )

        auditoria = registrar_auditoria(
            {**estado, "auditoria": auditoria},
            nodo="depurar_duplicados",
            decision="continuar",
            motivo=(
                f"Se conservan {len(validos)} de {len(estado['candidatos'])} perfiles; "
                f"se descartaron {len(duplicados)} duplicados."
            ),
        )

    return {
        "candidatos_filtrados": validos,
        "duplicados": duplicados,
        "indice_candidato": 0,
        "auditoria": auditoria,
    }


def _puntaje_sin_fecha(candidato: dict, vacante: dict, config: Configuracion) -> float:
    """Puntaje que tendría el perfil si el reclutador diera la fecha.

    Sirve para ordenar a quién preguntar primero cuando hay más perfiles con
    datos faltantes que consultas disponibles (RNF-04).
    """

    supuesto = dict(candidato)
    supuesto["availability_date"] = str(
        vacante.get("availability_required") or "9999-12-31"
    )
    return evaluar_candidato(supuesto, vacante, config)["puntaje"]


def consultar_reclutador_nodo(estado: EstadoAgente) -> dict:
    """Pregunta al reclutador simulado los datos faltantes (RF-04).

    Solo se consultan los candidatos únicos y con datos faltantes. El máximo
    de consultas (`recruiter.max_queries`) limita cuántas preguntas se hacen;
    las que quedan fuera del límite se registran como tal y el dato sigue
    desconocido. La respuesta se usa para puntuar; el dataset no se modifica.
    """

    config: Configuracion = estado["configuracion"]
    respuestas = cargar_respuestas()

    preguntas_por_candidato: dict[str, list[dict]] = {}
    consultas: list[dict] = []
    auditoria = estado["auditoria"]

    # La fecha pesa solo 5 puntos, pero sin ella el perfil no cumple los
    # requisitos duros. Por eso se pregunta primero a los perfiles que más
    # se acercan al puesto: si el límite de consultas se gastara en perfiles
    # que no cumplen skills o experiencia, se perderían los candidatos que
    # sí podrían entrar.
    candidatos_por_prioridad = sorted(
        estado["candidatos_filtrados"],
        key=lambda candidato: (
            -_puntaje_sin_fecha(candidato, estado["vacante_actual"], config),
            candidato.get("id", ""),
        ),
    )

    for candidato in candidatos_por_prioridad:
        _, preguntas = consultar_candidato(candidato, respuestas)
        if not preguntas:
            continue

        preguntas_por_candidato[candidato.get("id", "")] = []
        for pregunta in preguntas:
            if len(consultas) < config.max_consultas_reclutador:
                consultas.append(pregunta)
                preguntas_por_candidato[candidato.get("id", "")].append(pregunta)
            else:
                consultas.append(
                    {
                        **pregunta,
                        "resultado": "limite_alcanzado",
                        "motivo": (
                            "No se preguntó: se alcanzó el máximo de "
                            f"{config.max_consultas_reclutador} consultas al "
                            "reclutador; el dato sigue desconocido."
                        ),
                    }
                )

    candidatos = [
        _candidato_actualizado(
            candidato, preguntas_por_candidato.get(candidato.get("id", ""), [])
        )
        for candidato in estado["candidatos_filtrados"]
    ]

    for pregunta in consultas:
        auditoria = registrar_auditoria(
            {**estado, "auditoria": auditoria},
            nodo="consultar_reclutador",
            decision=pregunta["resultado"],
            motivo=f"Candidato {pregunta['candidato_id']}: {pregunta['motivo']}",
        )

    respondidas = len([c for c in consultas if c["resultado"] == "respondida"])
    auditoria = registrar_auditoria(
        {**estado, "auditoria": auditoria},
        nodo="consultar_reclutador",
        decision="continuar",
        motivo=(
            f"{respondidas} datos faltantes respondidos por el reclutador; "
            f"se evaluarán {len(candidatos)} perfiles."
        ),
    )

    return {
        "candidatos_filtrados": candidatos,
        "consultas_reclutador": estado["consultas_reclutador"] + consultas,
        "auditoria": auditoria,
    }


def procesar_candidato(estado: EstadoAgente) -> dict:
    """Evalúa un candidato, lo puntúa y registra la decisión en la auditoría.

    La puntuación es determinista y la justificación sale de una plantilla
    cuando el modo sin LLM está activo (RNF-02, RNF-03).
    """

    indice = estado["indice_candidato"]
    candidatos = estado["candidatos_filtrados"]

    if indice >= len(candidatos):
        return {"estado": "candidatos_recorridos"}

    candidato = candidatos[indice]
    identificador = candidato.get("id", "sin ID")
    config: Configuracion = estado["configuracion"]
    evaluacion = evaluar_candidato(candidato, estado["vacante_actual"], config)

    justificacion = evaluacion["motivo"]
    modo = "plantilla"
    llm_calls = estado["llm_calls"]
    errores = estado["errores"]

    # El puntaje siempre es código (RF-03). Con LLM solo cambia el texto.
    if not config.sin_llm and llm_calls < config.max_llamadas_llm:
        justificacion, llm_calls, error = _justificar_con_llm(
            estado, candidato, evaluacion, llm_calls
        )
        if error:
            errores = errores + [error]
        else:
            modo = "llm"

    resultados = estado["resultados"] + [
        {
            "id": identificador,
            **evaluacion,
            "justificacion": justificacion,
            "modo_justificacion": modo,
        }
    ]

    fuente = "Justificación por plantilla (modo sin LLM)." if config.sin_llm else ""
    motivo = (
        f"Candidato {identificador}: {evaluacion['puntaje']:g} puntos; "
        f"{'cumple' if evaluacion['cumple_requisitos'] else 'no cumple'} "
        f"los requisitos obligatorios. {fuente}"
    ).strip()

    return {
        "indice_candidato": indice + 1,
        "iteracion": estado["iteracion"] + 1,
        "resultados": resultados,
        "llm_calls": llm_calls,
        "errores": errores,
        "auditoria": registrar_auditoria(
            estado,
            nodo="procesar_candidato",
            decision="evaluar_candidato",
            motivo=motivo,
            iteracion=estado["iteracion"] + 1,
        ),
    }


def _justificar_con_llm(
    estado: EstadoAgente,
    candidato: dict,
    evaluacion: dict,
    llm_calls: int,
) -> tuple[str, int, str]:
    """Pide la justificación a OpenRouter y devuelve (texto, llamadas, error)."""

    from src.llm_cliente import ErrorLLM, crear_llm, generar_justificacion

    try:
        llm = estado.get("llm") or crear_llm()
        texto = generar_justificacion(
            llm, candidato, estado["vacante_actual"], evaluacion
        )
    except ErrorLLM as error:
        return evaluacion["motivo"], llm_calls, f"LLM no disponible: {error}"
    except Exception as error:  # red, cuota o modelo inválido
        return (
            evaluacion["motivo"],
            llm_calls,
            f"Falló la llamada al LLM: {type(error).__name__}: {error}",
        )

    return texto, llm_calls + 1, ""


def generar_shortlist_nodo(estado: EstadoAgente) -> dict:
    """Evalúa a todos los candidatos y arma la shortlist vigente.

    `calificados` guarda la evaluación de todos los perfiles; `shortlist`
    solo los que ocupan puesto (cumplen todos los requisitos y el umbral).
    """

    config: Configuracion = estado["configuracion"]
    shortlist = construir_shortlist(
        estado["candidatos_filtrados"],
        estado["vacante_actual"],
        config,
    )

    # Se recalifica a todos para saber quién supera el umbral, aunque el
    # perfil no tenga puesto por rol o modalidad. El orden es el mismo que
    # el de la shortlist: puntaje descendente y luego ID ascendente.
    evaluados = [
        {
            "id": candidato.get("id", ""),
            **evaluar_candidato(candidato, estado["vacante_actual"], config),
        }
        for candidato in estado["candidatos_filtrados"]
    ]
    evaluados.sort(key=lambda item: (-item["puntaje"], item["id"]))

    posiciones = {item["id"]: item["posicion"] for item in shortlist}
    for item in evaluados:
        if item["id"] in posiciones:
            item["posicion"] = posiciones[item["id"]]

    return {
        "shortlist": shortlist,
        "calificados": evaluados,
        "auditoria": registrar_auditoria(
            estado,
            nodo="generar_shortlist",
            decision="shortlist_generada",
            motivo=(
                f"Se evaluaron {len(estado['candidatos_filtrados'])} candidatos únicos; "
                f"la shortlist queda con {len(shortlist)} perfiles "
                f"(umbral {config.threshold:g}, orden por puntaje y luego por ID)."
            ),
        ),
    }


def evaluar_resultado_nodo(estado: EstadoAgente) -> dict:
    """Evalúa si la vacante tuvo éxito (RF-05).

    Hay éxito si al menos 3 candidatos superan el umbral. Si hay éxito, el
    flujo termina; si no, se relajan criterios en el orden configurado.
    """

    config: Configuracion = estado["configuracion"]
    evaluacion = ajustar_a_shortlist(
        evaluar_resultado(estado["calificados"], config),
        estado["shortlist"],
        config.shortlist_size,
    )
    decision = "exito" if evaluacion["exito"] else "insuficientes"

    # Hay éxito, pero la shortlist todavía tiene puestos libres: se relaja
    # también, porque el objetivo es dejar 3 perfiles en los puestos.
    if evaluacion["exito"] and evaluacion["puestos_libres"] == 0:
        decision = "exito"
    elif evaluacion["exito"]:
        decision = "exito_parcial"

    if decision == "exito":
        motivo = (
            f"Éxito: {evaluacion['aptos']} candidatos superan el umbral "
            f"{config.threshold:g} (mínimo {evaluacion['minimo']}) y la "
            f"shortlist está completa con {evaluacion['cubiertos']} perfiles."
        )
    elif decision == "exito_parcial":
        motivo = (
            f"Éxito: {evaluacion['aptos']} candidatos superan el umbral "
            f"{config.threshold:g}, pero solo {evaluacion['cubiertos']} ocupan "
            f"puesto; quedan {evaluacion['puestos_libres']} sin cubrir. "
            "Se intentan relajaciones."
        )
    else:
        motivo = (
            f"Solo {evaluacion['aptos']} candidatos superan el umbral "
            f"{config.threshold:g}; se requieren {evaluacion['minimo']}. "
            f"Puestos sin cubrir: {evaluacion['puestos_libres']}."
        )

    return {
        "evaluacion": evaluacion,
        "analisis_shortlist": explicar_shortlist_incompleta(
            estado["calificados"],
            estado["vacante_actual"],
            estado["shortlist"],
            config,
        ),
        "decision_actual": decision,
        "auditoria": registrar_auditoria(
            estado,
            nodo="evaluar_resultado",
            decision=decision,
            motivo=motivo,
        ),
    }


def relajar_criterios(estado: EstadoAgente) -> dict:
    """Aplica la siguiente relajación en el orden configurado (RF-06).

    Los skills obligatorios nunca se relajan. Si ya no quedan criterios o
    se alcanzó el máximo de relajaciones, la vacante se cierra como
    incompleta.
    """

    config: Configuracion = estado["configuracion"]
    vacante_nueva, relajacion, resultado = aplicar_relajacion(
        estado["vacante_actual"],
        estado["relajaciones_aplicadas"],
        config,
    )

    if relajacion is None:
        motivo = (
            f"No quedan criterios por relajar o se alcanzó el máximo de "
            f"{config.max_relajaciones} relajaciones. La vacante queda incompleta."
        )
        evaluacion = estado.get("evaluacion") or {}
        if evaluacion.get("puestos_libres"):
            motivo += (
                f" Se entregan los {evaluacion.get('cubiertos', 0)} perfiles que "
                f"sí cumplen y quedan {evaluacion['puestos_libres']} puestos sin cubrir "
                "(RF-07)."
            )
        return {
            "estado": "incompleta",
            "requiere_revision_humana": True,
            # "sin_relajaciones" cierra la corrida: no vuelve al loop.
            "decision_actual": "finalizar",
            "auditoria": registrar_auditoria(
                estado,
                nodo="relajar_criterios",
                decision="sin_relajaciones",
                motivo=motivo,
            ),
        }

    relajacion = {
        **relajacion,
        "iteracion": len(estado["relajaciones_aplicadas"]) + 1,
    }

    return {
        "vacante_actual": vacante_nueva,
        "relajaciones_aplicadas": estado["relajaciones_aplicadas"] + [relajacion],
        "indice_candidato": 0,
        "decision_actual": "relajar",
        "auditoria": registrar_auditoria(
            estado,
            nodo="relajar_criterios",
            decision=f"relajar_{relajacion['tipo']}",
            motivo=(
                f"Relajación {relajacion['iteracion']}/{config.max_relajaciones}: "
                f"{relajacion['descripcion']} Los skills obligatorios no se relajan."
            ),
        ),
    }


def decidir_siguiente_paso(estado: EstadoAgente) -> dict:
    """Decide si continúa el loop o finaliza, y lo registra en la auditoría."""

    if estado["errores"]:
        decision = "error"
        motivo = "El flujo tiene errores registrados."
    elif estado["indice_candidato"] < len(estado["candidatos_filtrados"]):
        decision = "repetir"
        motivo = (
            f"Quedan candidatos por revisar "
            f"({estado['indice_candidato']} de "
            f"{len(estado['candidatos_filtrados'])})."
        )
    else:
        decision = "finalizar"
        motivo = (
            f"Se revisaron los {len(estado['candidatos_filtrados'])} "
            f"candidatos únicos disponibles."
        )

    # "decision_actual" guarda la decisión para que el grafo sepa a dónde ir.
    return {
        "decision_actual": decision,
        "motivo_actual": motivo,
        "auditoria": registrar_auditoria(
            estado,
            nodo="decidir_siguiente_paso",
            decision=decision,
            motivo=motivo,
        ),
    }


def finalizar(estado: EstadoAgente) -> dict:
    """Finaliza el recorrido de candidatos.

    Si tras las relajaciones la shortlist no se completa, se entregan los
    perfiles que sí cumplen y se explica qué requisito lo impide (RF-07).
    """

    evaluacion = estado.get("evaluacion") or {}
    analisis = estado.get("analisis_shortlist") or {}

    if estado["errores"]:
        motivo = "El flujo terminó con errores."
    elif estado["estado"] == "incompleta":
        entregados = analisis.get("puestos_llenos", len(estado["shortlist"]))
        motivo = (
            f"Tras {len(estado['relajaciones_aplicadas'])} relajaciones la shortlist "
            f"no se completa: se entregan {entregados} de "
            f"{entregados + analisis.get('puestos_libres', 0)} perfiles. "
            f"{analisis.get('motivo_principal', '')}"
        ).strip()
    else:
        motivo = (
            f"Terminó el recorrido con {len(estado['candidatos_filtrados'])} "
            f"candidatos únicos, {len(estado['shortlist'])} en la shortlist, "
            f"{evaluacion.get('aptos', 0)} sobre el umbral y "
            f"{len(estado['relajaciones_aplicadas'])} relajaciones aplicadas."
        )

    if estado["errores"]:
        estado_final = "error"
    elif estado["estado"] == "incompleta":
        estado_final = "incompleta"
    else:
        estado_final = "finalizado"

    return {
        "estado": estado_final,
        "auditoria": registrar_auditoria(
            estado,
            nodo="finalizar",
            decision="finalizar" if estado_final != "error" else "error",
            motivo=motivo,
        ),
    }


def decidir_tras_resultado(estado: EstadoAgente) -> str:
    """Si no hay éxito pleno, se intenta relajar; si no se puede, se cierra."""

    return "exito" if estado["decision_actual"] == "exito" else "insuficientes"


def construir_grafo():
    """Construye el grafo: validación, duplicados, loop, éxito y relajación.

    Flujo:
    validar -> duplicados -> consultar_reclutador -> loop de candidatos
    -> shortlist -> evaluar_resultado -> (exito | relajar -> loop)
    -> finalizar.
    """

    grafo = StateGraph(EstadoAgente)

    # `pasos_grafo` es un canal sumable: cada nodo aporta 1 al contador real de
    # LangGraph, así se puede comparar con `recursion_limit` (RNF-04).
    for nombre, nodo in (
        ("validar_estado", validar_estado),
        ("depurar_duplicados", depurar_duplicados_nodo),
        ("consultar_reclutador", consultar_reclutador_nodo),
        ("procesar_candidato", procesar_candidato),
        ("decidir_siguiente_paso", decidir_siguiente_paso),
        ("generar_shortlist", generar_shortlist_nodo),
        ("evaluar_resultado", evaluar_resultado_nodo),
        ("relajar_criterios", relajar_criterios),
        ("finalizar", finalizar),
    ):
        grafo.add_node(nombre, _contando_pasos(nodo, contar_paso))

    # `pasos_grafo` arranca en 0 (estado inicial), igual que el contador de
    # LangGraph en la primera ejecución.
    grafo.add_edge(START, "validar_estado")

    grafo.add_conditional_edges(
        "validar_estado",
        lambda estado: "error" if estado["errores"] else "continuar",
        {
            "error": END,
            "continuar": "depurar_duplicados",
        },
    )

    grafo.add_edge("depurar_duplicados", "consultar_reclutador")

    grafo.add_edge("consultar_reclutador", "procesar_candidato")

    grafo.add_edge("procesar_candidato", "decidir_siguiente_paso")

    grafo.add_conditional_edges(
        "decidir_siguiente_paso",
        lambda estado: estado["decision_actual"],
        {
            "repetir": "procesar_candidato",
            "finalizar": "generar_shortlist",
            "error": END,
        },
    )

    grafo.add_edge("generar_shortlist", "evaluar_resultado")

    grafo.add_conditional_edges(
        "evaluar_resultado",
        decidir_tras_resultado,
        {
            "exito": "finalizar",
            "insuficientes": "relajar_criterios",
        },
    )

    # Si ya no cabe otra relajación, `relajar_criterios` deja `finalizar` y
    # la corrida cierra con la shortlist parcial y su explicación (RF-07).
    grafo.add_conditional_edges(
        "relajar_criterios",
        lambda estado: estado["decision_actual"],
        {
            "relajar": "procesar_candidato",
            "finalizar": "finalizar",
        },
    )

    grafo.add_edge("finalizar", END)

    return grafo.compile()


app_matching = construir_grafo()
