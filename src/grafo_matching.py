
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

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
    """Agrega un evento al log de auditorÃ­a (RF-10).

    Cada evento contiene siempre: iteraciÃ³n, nodo, decisiÃ³n y motivo.
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
        # Cada ejecuciÃ³n del nodo aporta un paso al contador sumable.
        return {**(resultado or {}), **paso_actual(estado)}

    return envuelto


def validar_estado(estado: EstadoAgente) -> dict:
    """Comprueba la vacante, los candidatos y la configuraciÃ³n (RNF-02)."""

    errores = []

    if not estado["vacante_actual"]:
        errores.append("No se recibiÃ³ una vacante para procesar.")

    if not isinstance(estado["candidatos"], list):
        errores.append("La lista de candidatos no tiene un formato vÃ¡lido.")

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
            "errores": estado["errores"] + [f"ConfiguraciÃ³n invÃ¡lida: {error}"],
            "estado": "error",
            "auditoria": registrar_auditoria(
                estado,
                nodo="validar_estado",
                decision="error",
                motivo=f"ConfiguraciÃ³n invÃ¡lida: {error}",
            ),
        }

    modo = "sin LLM" if config.sin_llm else "con LLM"
    auditoria = registrar_auditoria(
        estado,
        nodo="validar_estado",
        decision="continuar",
        motivo=(
            f"Vacante '{estado['vacante_actual'].get('id', 'sin ID')}' vÃ¡lida y "
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
            motivo=f"Los {len(validos)} perfiles son Ãºnicos.",
        )
    else:
        for duplicado in duplicados:
            auditoria = registrar_auditoria(
                {**estado, "auditoria": auditoria},
                nodo="depurar_duplicados",
                decision="descartar_duplicado",
                motivo=(
                    f"{duplicado['id']} ({duplicado['nombre']}) se descarta por: "
                    f"{duplicado['motivo']} con el perfil Ãºnico "
                    f"{duplicado['conservado_id']} (posiciÃ³n {duplicado['posicion']})."
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
    """Puntaje que tendrÃ­a el perfil si el reclutador diera la fecha.

    Sirve para ordenar a quiÃ©n preguntar primero cuando hay mÃ¡s perfiles con
    datos faltantes que consultas disponibles (RNF-04).
    """

    supuesto = dict(candidato)
    supuesto["availability_date"] = str(
        vacante.get("availability_required") or "9999-12-31"
    )
    return evaluar_candidato(supuesto, vacante, config)["puntaje"]


def consultar_reclutador_nodo(estado: EstadoAgente) -> dict:
    """Pregunta al reclutador simulado los datos faltantes (RF-04).

    Solo se consultan los candidatos Ãºnicos y con datos faltantes. El mÃ¡ximo
    de consultas (`recruiter.max_queries`) limita cuÃ¡ntas preguntas se hacen;
    las que quedan fuera del lÃ­mite se registran como tal y el dato sigue
    desconocido. La respuesta se usa para puntuar; el dataset no se modifica.
    """

    config: Configuracion = estado["configuracion"]
    respuestas = cargar_respuestas()

    preguntas_por_candidato: dict[str, list[dict]] = {}
    consultas: list[dict] = []
    auditoria = estado["auditoria"]

    # La fecha pesa solo 5 puntos, pero sin ella el perfil no cumple los
    # requisitos duros. Por eso se pregunta primero a los perfiles que mÃ¡s
    # se acercan al puesto: si el lÃ­mite de consultas se gastara en perfiles
    # que no cumplen skills o experiencia, se perderÃ­an los candidatos que
    # sÃ­ podrÃ­an entrar.
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
                            "No se preguntÃ³: se alcanzÃ³ el mÃ¡ximo de "
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
            f"se evaluarÃ¡n {len(candidatos)} perfiles."
        ),
    )

    return {
        "candidatos_filtrados": candidatos,
        "consultas_reclutador": estado["consultas_reclutador"] + consultas,
        "auditoria": auditoria,
    }


def procesar_candidato(estado: EstadoAgente) -> dict:
    """EvalÃºa un candidato, lo puntÃºa y registra la decisiÃ³n en la auditorÃ­a.

    La puntuaciÃ³n es determinista y la justificaciÃ³n sale de una plantilla
    cuando el modo sin LLM estÃ¡ activo (RNF-02, RNF-03).
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
    audit_llm = estado["auditoria"]

    # El puntaje siempre es cÃ³digo (RF-03). Con LLM solo cambia el texto.
    if not config.sin_llm and llm_calls < config.max_llamadas_llm:
        justificacion, llm_calls, modo, error = _justificar_con_llm(
            estado, candidato, evaluacion, llm_calls
        )
        if error:
            # RNF-08: el fallo del LLM (tras el reintento) queda en el log.
            errores = errores + [error]
            audit_llm = registrar_auditoria(
                {**estado, "auditoria": audit_llm},
                nodo="procesar_candidato",
                decision="fallback_plantilla",
                motivo=f"Candidato {identificador}: {error} Se usÃ³ la plantilla.",
                iteracion=estado["iteracion"] + 1,
            )

    resultados = estado["resultados"] + [
        {
            "id": identificador,
            **evaluacion,
            "justificacion": justificacion,
            "modo_justificacion": modo,
        }
    ]

    fuente = "JustificaciÃ³n por plantilla (modo sin LLM)." if config.sin_llm else ""
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
            {**estado, "auditoria": audit_llm},
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
) -> tuple[str, int, str, str]:
    """Pide la justificaciÃ³n al LLM y devuelve (texto, llamadas, fuente, error).

    RNF-08: se reintenta una vez y, si el LLM sigue fallando o devuelve un
    formato invÃ¡lido, se usa la justificaciÃ³n por plantilla. La fuente queda
    como `llm` o `plantilla`.
    """

    from src.llm_cliente import (
        crear_llm,
        generar_justificacion_con_fallback,
        resumir_error,
    )

    try:
        llm = estado.get("llm") or crear_llm()
        texto, fuente, error = generar_justificacion_con_fallback(
            llm, candidato, estado["vacante_actual"], evaluacion
        )
    except Exception as error:  # ni se pudo crear el cliente
        return (
            evaluacion["motivo"],
            llm_calls,
            "plantilla",
            f"LLM no disponible: {resumir_error(error)}",
        )

    if fuente == "llm":
        return texto, llm_calls + 1, "llm", ""

    # Se intentÃ³ una vez mÃ¡s antes de rendirse; las 2 llamadas cuentan al tope.
    # Si la cuota se agotÃ³, el resto de la corrida usa la plantilla sin volver
    # a llamar al LLM (RNF-04): no se gasta una llamada que ya no cabe.
    return texto, estado["configuracion"].max_llamadas_llm, "plantilla", (
        f"LLM no disponible: {error}"
    )


def generar_shortlist_nodo(estado: EstadoAgente) -> dict:
    """EvalÃºa a todos los candidatos y arma la shortlist vigente.

    `calificados` guarda la evaluaciÃ³n de todos los perfiles; `shortlist`
    solo los que ocupan puesto (cumplen todos los requisitos y el umbral).
    """

    config: Configuracion = estado["configuracion"]
    shortlist = construir_shortlist(
        estado["candidatos_filtrados"],
        estado["vacante_actual"],
        config,
    )

    # Se recalifica a todos para saber quiÃ©n supera el umbral, aunque el
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

    # RF-08: perfiles de reserva. Son los aptos que superan el umbral y no
    # ocupan puesto porque la shortlist ya está llena; si el humano rechaza a
    # alguien, el reemplazo sale de aquí. No se presentan ni se aprueban hasta
    # que haga falta, así la shortlist sigue teniendo los puestos de la vacante.
    reserva = [
        item
        for item in evaluados
        if item["cumple_requisitos"]
        and item["puntaje"] >= config.threshold
        and item["id"] not in posiciones
    ]

    return {
        "shortlist": shortlist,
        "calificados": evaluados,
        "reserva": reserva,
        "auditoria": registrar_auditoria(
            estado,
            nodo="generar_shortlist",
            decision="shortlist_generada",
            motivo=(
                f"Se evaluaron {len(estado['candidatos_filtrados'])} candidatos Ãºnicos; "
                f"la shortlist queda con {len(shortlist)} perfiles "
                f"(umbral {config.threshold:g}, orden por puntaje y luego por ID)."
            ),
        ),
    }


def evaluar_resultado_nodo(estado: EstadoAgente) -> dict:
    """EvalÃºa si la vacante tuvo Ã©xito (RF-05).

    Hay Ã©xito si al menos 3 candidatos superan el umbral. Si hay Ã©xito, el
    flujo termina; si no, se relajan criterios en el orden configurado.
    """

    config: Configuracion = estado["configuracion"]
    evaluacion = ajustar_a_shortlist(
        evaluar_resultado(estado["calificados"], config),
        estado["shortlist"],
        config.shortlist_size,
    )
    decision = "exito" if evaluacion["exito"] else "insuficientes"

    # Hay Ã©xito, pero la shortlist todavÃ­a tiene puestos libres: se relaja
    # tambiÃ©n, porque el objetivo es dejar 3 perfiles en los puestos.
    if evaluacion["exito"] and evaluacion["puestos_libres"] == 0:
        decision = "exito"
    elif evaluacion["exito"]:
        decision = "exito_parcial"

    if decision == "exito":
        motivo = (
            f"Ã‰xito: {evaluacion['aptos']} candidatos superan el umbral "
            f"{config.threshold:g} (mÃ­nimo {evaluacion['minimo']}) y la "
            f"shortlist estÃ¡ completa con {evaluacion['cubiertos']} perfiles."
        )
    elif decision == "exito_parcial":
        motivo = (
            f"Ã‰xito: {evaluacion['aptos']} candidatos superan el umbral "
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
    """Aplica la siguiente relajaciÃ³n en el orden configurado (RF-06).

    Los skills obligatorios nunca se relajan. Si ya no quedan criterios o
    se alcanzÃ³ el mÃ¡ximo de relajaciones, la vacante se cierra como
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
            f"No quedan criterios por relajar o se alcanzÃ³ el mÃ¡ximo de "
            f"{config.max_relajaciones} relajaciones. La vacante queda incompleta."
        )
        evaluacion = estado.get("evaluacion") or {}
        if evaluacion.get("puestos_libres"):
            motivo += (
                f" Se entregan los {evaluacion.get('cubiertos', 0)} perfiles que "
                f"sÃ­ cumplen y quedan {evaluacion['puestos_libres']} puestos sin cubrir "
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
                f"RelajaciÃ³n {relajacion['iteracion']}/{config.max_relajaciones}: "
                f"{relajacion['descripcion']} Los skills obligatorios no se relajan."
            ),
        ),
    }


def decidir_siguiente_paso(estado: EstadoAgente) -> dict:
    """Decide si continÃºa el loop o finaliza, y lo registra en la auditorÃ­a.

    RNF-08: un fallo del LLM ya se resolviÃ³ con la justificaciÃ³n por plantilla
    y solo queda registrado; no corta el recorrido de candidatos. SÃ­ corta un
    error que impide seguir (datos o configuraciÃ³n, que pone `estado`=error en
    `validar_estado`).
    """

    if estado.get("estado") == "error":
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
            f"candidatos Ãºnicos disponibles."
        )

    # "decision_actual" guarda la decisiÃ³n para que el grafo sepa a dÃ³nde ir.
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
    perfiles que sÃ­ cumplen y se explica quÃ© requisito lo impide (RF-07).
    """

    evaluacion = estado.get("evaluacion") or {}
    analisis = estado.get("analisis_shortlist") or {}
    aprobacion = estado.get("aprobacion") or {}

    if estado.get("estado") == "error":
        motivo = "El flujo terminÃ³ con errores."
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
            f"TerminÃ³ el recorrido con {len(estado['candidatos_filtrados'])} "
            f"candidatos Ãºnicos, {len(estado['shortlist'])} en la shortlist, "
            f"{evaluacion.get('aptos', 0)} sobre el umbral y "
            f"{len(estado['relajaciones_aplicadas'])} relajaciones aplicadas."
        )

    # RF-08: quÃ© hizo la persona con la shortlist antes de cerrar.
    if aprobacion:
        rechazados = aprobacion.get("rechazados") or []
        if rechazados:
            motivo += (
                f" AprobaciÃ³n humana ({aprobacion.get('estado', 'aprobada')}): "
                f"rechazÃ³ {', '.join(rechazados)} y la shortlist final se armÃ³ con "
                f"{', '.join(aprobacion.get('aprobados') or []) or 'ningÃºn perfil'}."
            )
        elif aprobacion.get("aprobados"):
            motivo += (
                " La shortlist fue aprobada por la persona revisora "
                f"({', '.join(aprobacion['aprobados'])})."
            )

    if estado.get("estado") == "error":
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
    """Si no hay Ã©xito pleno, se intenta relajar; si no se puede, se cierra."""

    return "exito" if estado["decision_actual"] == "exito" else "insuficientes"


def devolver_rechazados(calificados: list[dict]) -> list[dict]:
    """Perfiles que vuelven a competir tras un rechazo humano (RF-08).

    La shortlist se arma solo con aptos; si el humano descarta a uno, el
    reemplazo tiene que salir de los perfiles que superan el umbral (aunque
    les faltara algÃºn deseable). Los que no lo superan tampoco pueden ocupar
    el puesto de un rechazado.
    """

    return [item for item in calificados if item["cumple_requisitos"]]


def _presentar_shortlist(estado: EstadoAgente) -> dict:
    """Shortlist que el humano revisa en el interrupt (RF-08)."""

    config: Configuracion = estado["configuracion"]
    return {
        "tipo": "aprobacion_shortlist",
        "mensaje": (
            "Revise la shortlist antes de cerrar. Responda con los IDs que "
            "rechaza; los demÃ¡s se aprueban y se busca reemplazo para cada rechazado."
        ),
        "vacante_id": estado["vacante_actual"].get("id", ""),
        "revision": estado.get("aprobacion_revision", 0) + 1,
        "rechazados_previos": list(estado.get("candidatos_rechazados") or []),
        "shortlist": [
            {
                "posicion": item["posicion"],
                "id": item["id"],
                "puntaje": item["puntaje"],
                "cumple_requisitos": item["cumple_requisitos"],
                "justificacion": item["justificacion"],
            }
            for item in estado["shortlist"]
        ],
        "formato_respuesta": (
            "{'rechazar': [ids]} o {candidato_id: 'rechazar'}; vacÃ­o = aprobar todo"
        ),
        "limite_revisiones": config.max_revisiones_aprobacion,
        # RF-08: si se rechaza a alguien, el reemplazo sale de estos perfiles
        # aptos que superan el umbral y no ocupan puesto.
        "reemplazos_disponibles": [
            {"id": item["id"], "puntaje": item["puntaje"]}
            for item in estado.get("reserva") or []
        ],
    }


def interpretar_respuesta_humana(respuesta, shortlist: list[dict]) -> list[str]:
    """IDs rechazados por el humano (RF-08).

    Acepta una lista de IDs, un dict {id: 'rechazar'} o un dict con la clave
    `rechazar`. Los IDs que no estÃ¡n en la shortlist se ignoran y, si no hay
    respuesta, se aprueba toda la shortlist.
    """

    ids = {item["id"] for item in shortlist}
    if respuesta is None or respuesta == "":
        return []

    if isinstance(respuesta, dict):
        if "rechazar" in respuesta:
            valores = respuesta["rechazar"]
        else:
            valores = [
                cid for cid, decision in respuesta.items()
                if str(decision).strip().lower() == "rechazar"
            ]
    else:
        valores = respuesta

    if isinstance(valores, str):
        valores = [valores]
    return [str(cid) for cid in (valores or []) if str(cid) in ids]


def _buscar_reemplazo(
    estado: EstadoAgente,
    excluidos: set[str],
    descartados: list[dict] | None = None,
) -> dict | None:
    """Siguiente perfil apto sobre el umbral que no estÃ¡ ni aprobado ni rechazado.

    `calificados` ya viene ordenado por puntaje descendente y luego por ID
    (`generar_shortlist`), asÃ­ que el primero que quede libre es el reemplazo.
    Los perfiles que se revisaron y no servÃ­an se agregan a `descartados` con
    el motivo, para que la auditorÃ­a diga por quÃ© no hubo reemplazo.
    """

    config: Configuracion = estado["configuracion"]
    # Primero los perfiles de reserva (aptos y sin puesto); si no queda
    # ninguno, se revisa el resto de calificados por si una relajación dejó
    # apto a alguien que antes no lo estaba.
    candidatos = list(estado.get("reserva") or []) + list(estado.get("calificados") or [])
    vistos: set[str] = set()
    for evaluado in candidatos:
        if evaluado["id"] in excluidos or evaluado["id"] in vistos:
            continue
        vistos.add(evaluado["id"])
        # Se vuelve a puntuar con los criterios vigentes de la vacante.
        # `calificados` muestra los requisitos de la Ãºltima relajaciÃ³n, asÃ­ que
        # un perfil que solo cumple con el criterio original no entra.
        actual = evaluar_candidato(
            next(
                (
                    c
                    for c in estado["candidatos_filtrados"]
                    if c.get("id") == evaluado["id"]
                ),
                {},
            ),
            estado["vacante_actual"],
            config,
        )
        if not actual["cumple_requisitos"] or actual["puntaje"] < config.threshold:
            if descartados is not None:
                descartados.append(
                    {
                        "id": evaluado["id"],
                        "puntaje": actual["puntaje"],
                        "motivo": actual["motivo"],
                    }
                )
            continue
        return {
            "id": evaluado["id"],
            **actual,
            "posicion": 0,
            "justificacion": actual["motivo"],
            "supera_umbral": True,
        }
    return None





def aprobacion_humana_nodo(estado: EstadoAgente) -> dict:
    """Detiene el grafo para que una persona apruebe la shortlist (RF-08).

    Usa el `interrupt` de LangGraph: la corrida se pausa con la shortlist a
    revisar y espera `Command(resume=...)`. Si el humano rechaza a un
    candidato, se excluye de la shortlist, se busca un reemplazo entre los
    perfiles aptos restantes y, si lo hay, se vuelve a interrumpir para
    aprobar la shortlist nueva. Si no hay reemplazo, la vacante queda para
    revisiÃ³n humana.
    """

    shortlist = list(estado["shortlist"])
    if not shortlist:
        return {
            "aprobacion": {"estado": "sin_shortlist", "aprobados": [], "rechazados": []},
            "decision_actual": "finalizar",
            "auditoria": registrar_auditoria(
                estado,
                nodo="aprobacion_humana",
                decision="sin_shortlist",
                motivo="No hay perfiles en la shortlist: no se pide aprobaciÃ³n.",
            ),
        }

    config: Configuracion = estado["configuracion"]
    revision = estado.get("aprobacion_revision", 0) + 1
    rechazados = list(estado.get("candidatos_rechazados") or [])

    if revision > config.max_revisiones_aprobacion:
        # Se agotaron las rondas de revisiÃ³n: la shortlist vigente se aprueba.
        aprobados = [item["id"] for item in shortlist]
        return {
            "aprobacion_revision": revision,
            "decision_actual": "finalizar",
            "aprobacion": {
                "estado": "aprobada_por_limite",
                "aprobados": aprobados,
                "rechazados": rechazados,
                "revisiones": revision - 1,
            },
            "auditoria": registrar_auditoria(
                estado,
                nodo="aprobacion_humana",
                decision="aprobada_por_limite",
                motivo=(
                    f"Se alcanzÃ³ el lÃ­mite de {config.max_revisiones_aprobacion} "
                    f"revisiones: se aprueba la shortlist con {', '.join(aprobados)}."
                ),
            ),
        }

    if estado.get("interrupt_habilitado"):
        respuesta = interrupt(_presentar_shortlist(estado))
    else:
        # La corrida automÃ¡tica (bandeja, reportes) compila el grafo sin
        # checkpointer y no se detiene: la shortlist se aprueba tal cual y la
        # ronda queda registrada en la auditorÃ­a de todos modos (RF-08).
        respuesta = []

    esta_ronda = interpretar_respuesta_humana(respuesta, shortlist)

    auditoria = registrar_auditoria(
        estado,
        nodo="aprobacion_humana",
        decision="interrupt",
        motivo=(
            f"RevisiÃ³n {revision}: se presenta la shortlist al humano "
            f"({', '.join(item['id'] for item in shortlist)})."
        ),
    )

    rechazados = rechazados + [cid for cid in esta_ronda if cid not in rechazados]

    if not esta_ronda:
        aprobados = [item["id"] for item in shortlist]
        return {
            "aprobacion_revision": revision,
            "decision_actual": "finalizar",
            "aprobacion": {
                "estado": "aprobada",
                "aprobados": aprobados,
                "rechazados": rechazados,
                "revisiones": revision,
                # Puestos que quedaron sin cubrir por rechazos sin reemplazo.
                "puestos_sin_reemplazo": max(0, config.shortlist_size - len(shortlist)),
            },
            "auditoria": registrar_auditoria(
                {**estado, "auditoria": auditoria},
                nodo="aprobacion_humana",
                decision="shortlist_aprobada",
                motivo=f"El humano aprobÃ³ la shortlist: {', '.join(aprobados)}.",
            ),
        }

    # Ejecuta el rechazo: se excluye al candidato y se busca un reemplazo.
    shortlist_nueva = [item for item in shortlist if item["id"] not in esta_ronda]
    # Los perfiles de reserva (aptos, pero sin puesto) compiten por el puesto
    # libre; los que ya ocupan puesto no se mueven.
    excluidos = {item["id"] for item in shortlist_nueva} | set(rechazados)
    puestos = config.shortlist_size
    reserva = list(estado.get("reserva") or [])

    for cid in esta_ronda:
        auditoria = registrar_auditoria(
            {**estado, "auditoria": auditoria},
            nodo="aprobacion_humana",
            decision="rechazar_candidato",
            motivo=f"El humano rechazÃ³ a {cid}; se excluye y se busca reemplazo.",
        )
        descartados: list[dict] = []
        reemplazo = _buscar_reemplazo(estado, excluidos, descartados)
        if reemplazo is None:
            # Se dice por quÃ© no hubo reemplazo: los perfiles que se revisaron
            # y el requisito que no cumplÃ­an (RF-08/RF-10).
            detalle = ""
            if descartados:
                detalle = " Revisados sin Ã©xito: " + "; ".join(
                    f"{item['id']} ({item['puntaje']:g} puntos, {item['motivo']})"
                    for item in descartados[:3]
                ) + "."
            auditoria = registrar_auditoria(
                {**estado, "auditoria": auditoria},
                nodo="aprobacion_humana",
                decision="sin_reemplazo",
                motivo=(
                    f"No quedan perfiles aptos sobre el umbral {config.threshold:g} "
                    f"para reemplazar a {cid}; la vacante queda para revisiÃ³n humana."
                    + detalle
                ),
            )
            continue

        excluidos.add(reemplazo["id"])
        reserva = [item for item in reserva if item["id"] != reemplazo["id"]]
        shortlist_nueva.append({**reemplazo, "reemplaza_a": cid})
        auditoria = registrar_auditoria(
            {**estado, "auditoria": auditoria},
            nodo="aprobacion_humana",
            decision="reemplazo_encontrado",
            motivo=(
                f"Reemplazo para {cid}: {reemplazo['id']} "
                f"({reemplazo['puntaje']:g} puntos); se vuelve a pedir aprobaciÃ³n."
            ),
        )

    # El reemplazo ocupa el puesto del rechazado: la shortlist vuelve a tener
    # como máximo los puestos de la vacante (los demás quedan de reserva).
    shortlist_nueva.sort(key=lambda item: (-item["puntaje"], item["id"]))
    shortlist_nueva = shortlist_nueva[:puestos]
    for posicion, item in enumerate(shortlist_nueva, start=1):
        item["posicion"] = posicion

    return {
        "shortlist": shortlist_nueva,
        "reserva": reserva,
        "candidatos_rechazados": rechazados,
        "aprobacion_revision": revision,
        # Hay reemplazos por aprobar: el grafo vuelve al interrupt.
        "decision_actual": "revisar",
        "aprobacion": {
            "estado": "rechazo_pendiente_revision",
            "aprobados": [item["id"] for item in shortlist_nueva],
            "rechazados": rechazados,
            "revisiones": revision,
            # Puestos que quedaron sin cubrir porque no hubo reemplazo.
            "puestos_sin_reemplazo": max(0, puestos - len(shortlist_nueva)),
        },
        # La shortlist nueva vuelve al interrupt en la siguiente revisiÃ³n.
        "aprobacion_pendiente": _presentar_shortlist(
            {**estado, "shortlist": shortlist_nueva}
        ),
        "auditoria": auditoria,
    }


def _aprobacion_automatica(estado: EstadoAgente) -> dict:
    """Ronda de aprobaciÃ³n de la corrida automÃ¡tica, sin pausar (RF-08).

    La bandeja y los reportes no esperan a una persona: se registra la ronda
    en la auditorÃ­a y la shortlist se da por aprobada. La revisiÃ³n con
    `interrupt` real se hace con `python -m src.aprobacion`.
    """

    shortlist = list(estado["shortlist"])
    if not shortlist:
        return {
            "aprobacion": {"estado": "sin_shortlist", "aprobados": [], "rechazados": []},
            "decision_actual": "finalizar",
            "auditoria": registrar_auditoria(
                estado,
                nodo="aprobacion_humana",
                decision="sin_shortlist",
                motivo="No hay perfiles en la shortlist: no se pide aprobaciÃ³n.",
            ),
        }

    aprobados = [item["id"] for item in shortlist]
    revision = estado.get("aprobacion_revision", 0) + 1
    return {
        "aprobacion_revision": revision,
        "decision_actual": "finalizar",
        "aprobacion": {
            "estado": "aprobada",
            "aprobados": aprobados,
            "rechazados": list(estado.get("candidatos_rechazados") or []),
            "revisiones": revision,
            "pendiente_revision_humana": True,
        },
        "auditoria": registrar_auditoria(
            estado,
            nodo="aprobacion_humana",
            decision="shortlist_aprobada",
            motivo=(
                "La corrida automÃ¡tica no se detiene: la shortlist se aprueba "
                f"con {', '.join(aprobados)}. La aprobaciÃ³n con interrupt real se "
                "hace con `python -m src.aprobacion`."
            ),
        ),
    }


def construir_grafo(con_interrupt: bool = False):
    """Construye el grafo: validaciÃ³n, duplicados, loop, Ã©xito y aprobaciÃ³n.

    Flujo:
    validar -> duplicados -> consultar_reclutador -> loop de candidatos
    -> shortlist -> evaluar_resultado -> (exito | relajar -> loop)
    -> aprobacion_humana -> finalizar.

    `con_interrupt` indica si el `interrupt` de RF-08 puede pausar la corrida.
    Solo es asÃ­ con checkpointer (`compilar_con_aprobacion`): la corrida
    automÃ¡tica (bandeja, reportes) no se detiene y aprueba la shortlist tal
    cual, dejando la ronda en la auditorÃ­a.
    """

    grafo = StateGraph(EstadoAgente)

    # `pasos_grafo` es un canal sumable: cada nodo aporta 1 al contador real de
    # LangGraph, asÃ­ se puede comparar con `recursion_limit` (RNF-04).
    for nombre, nodo in (
        ("validar_estado", validar_estado),
        ("depurar_duplicados", depurar_duplicados_nodo),
        ("consultar_reclutador", consultar_reclutador_nodo),
        ("procesar_candidato", procesar_candidato),
        ("decidir_siguiente_paso", decidir_siguiente_paso),
        ("generar_shortlist", generar_shortlist_nodo),
        ("evaluar_resultado", evaluar_resultado_nodo),
        ("relajar_criterios", relajar_criterios),
        (
            "aprobacion_humana",
            aprobacion_humana_nodo if con_interrupt else _aprobacion_automatica,
        ),
        ("finalizar", finalizar),
    ):
        grafo.add_node(nombre, _contando_pasos(nodo, contar_paso))

    # `pasos_grafo` arranca en 0 (estado inicial), igual que el contador de
    # LangGraph en la primera ejecuciÃ³n.
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
            # RF-08: antes de cerrar, la shortlist pasa por aprobaciÃ³n humana.
            # Sin checkpointer el `interrupt` no puede pausar: esa ronda queda
            # registrada en la auditorÃ­a y la shortlist se aprueba tal cual.
            "exito": "aprobacion_humana",
            "insuficientes": "relajar_criterios",
        },
    )

    # Si ya no cabe otra relajaciÃ³n, `relajar_criterios` deja `finalizar` y
    # la corrida cierra con la shortlist parcial y su explicaciÃ³n (RF-07).
    grafo.add_conditional_edges(
        "relajar_criterios",
        lambda estado: estado["decision_actual"],
        {
            "relajar": "procesar_candidato",
            "finalizar": "finalizar",
        },
    )
    # RF-08: con reemplazos pendientes de aprobar el grafo vuelve al interrupt;
    # cuando la shortlist se aprueba (o se agotan las revisiones), cierra.
    grafo.add_conditional_edges(
        "aprobacion_humana",
        lambda estado: (
            "revisar" if estado.get("decision_actual") == "revisar" else "finalizar"
        ),
        {
            "revisar": "aprobacion_humana",
            "finalizar": "finalizar",
        },
    )

    grafo.add_edge("finalizar", END)

    return grafo.compile()


# La corrida automÃ¡tica (bandeja, reportes) no se detiene: la ronda de
# aprobaciÃ³n queda en la auditorÃ­a sin bloquear el proceso (RF-08). El grafo
# con checkpointer y `interrupt` real se arma con `compilar_con_aprobacion`.
app_matching = construir_grafo()


def compilar_con_aprobacion(estado_inicial: dict | None = None):
    """Grafo con memoria, para pausar en el interrupt de RF-08 y reanudarlo.

    Se usa desde `src.aprobacion` (CLI) y en las pruebas. El `interrupt` real
    necesita un checkpointer y un `thread_id` para poder reanudar con
    `Command(resume=...)`. Si se pasa `estado_inicial`, se le activa
    `interrupt_habilitado` para que la corrida sÃ­ se detenga.
    """

    if estado_inicial is not None:
        estado_inicial["interrupt_habilitado"] = True
    return construir_grafo(con_interrupt=True).copy({"checkpointer": MemorySaver()})


app_aprobacion = compilar_con_aprobacion()

