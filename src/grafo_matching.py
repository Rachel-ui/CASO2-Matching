
from langgraph.graph import StateGraph, START, END

from src.estado_agente import EstadoAgente


def validar_estado(estado: EstadoAgente) -> dict:
    """Comprueba que la vacante y los candidatos estén disponibles."""

    errores = []

    if not estado["vacante_actual"]:
        errores.append("No se recibió una vacante para procesar.")

    if not isinstance(estado["candidatos"], list):
        errores.append("La lista de candidatos no tiene un formato válido.")

    if errores:
        return {
            "errores": estado["errores"] + errores,
            "estado": "error",
            "auditoria": estado["auditoria"] + [
                {
                    "evento": "validacion_fallida",
                    "detalle": "; ".join(errores),
                }
            ],
        }

    return {
        "estado": "datos_validados",
        "indice_candidato": 0,
        "auditoria": estado["auditoria"] + [
            {
                "evento": "validacion_exitosa",
                "detalle": "La vacante y la lista de candidatos están disponibles.",
            }
        ],
    }


def procesar_candidato(estado: EstadoAgente) -> dict:
    """Recorre un candidato y registra el avance del loop."""

    indice = estado["indice_candidato"]
    candidatos = estado["candidatos"]

    if indice >= len(candidatos):
        return {"estado": "candidatos_recorridos"}

    candidato = candidatos[indice]

    return {
        "indice_candidato": indice + 1,
        "auditoria": estado["auditoria"] + [
            {
                "evento": "candidato_recorrido",
                "detalle": f"Candidato revisado: {candidato.get('id', 'sin ID')}.",
            }
        ],
    }


def decidir_siguiente_paso(estado: EstadoAgente) -> str:
    """Decide si continúa el loop o finaliza."""

    if estado["errores"]:
        return "error"

    if estado["indice_candidato"] < len(estado["candidatos"]):
        return "repetir"

    return "finalizar"


def finalizar(estado: EstadoAgente) -> dict:
    """Finaliza el recorrido básico de candidatos."""

    return {
        "estado": "finalizado" if not estado["errores"] else "error",
        "auditoria": estado["auditoria"] + [
            {
                "evento": "finalizacion",
                "detalle": (
                    "Terminó el recorrido de candidatos."
                    if not estado["errores"]
                    else "El flujo terminó con errores."
                ),
            }
        ],
    }


def construir_grafo():
    """Construye el grafo de práctica con loop condicional."""

    grafo = StateGraph(EstadoAgente)

    grafo.add_node("validar_estado", validar_estado)
    grafo.add_node("procesar_candidato", procesar_candidato)
    grafo.add_node("finalizar", finalizar)

    grafo.add_edge(START, "validar_estado")

    grafo.add_conditional_edges(
        "validar_estado",
        lambda estado: "error" if estado["errores"] else "continuar",
        {
            "error": END,
            "continuar": "procesar_candidato",
        },
    )

    grafo.add_conditional_edges(
        "procesar_candidato",
        decidir_siguiente_paso,
        {
            "repetir": "procesar_candidato",
            "finalizar": "finalizar",
            "error": END,
        },
    )

    grafo.add_edge("finalizar", END)

    return grafo.compile()


app_matching = construir_grafo()
