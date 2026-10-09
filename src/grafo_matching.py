
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
        "auditoria": estado["auditoria"] + [
            {
                "evento": "validacion_exitosa",
                "detalle": "La vacante y la lista de candidatos están disponibles.",
            }
        ],
    }


def finalizar(estado: EstadoAgente) -> dict:
    """Marca la ejecución inicial como finalizada."""

    return {
        "estado": "finalizado" if not estado["errores"] else "error",
        "auditoria": estado["auditoria"] + [
            {
                "evento": "finalizacion",
                "detalle": "Terminó el flujo básico de validación.",
            }
        ],
    }


def construir_grafo():
    """Construye el grafo básico del agente de matching."""

    grafo = StateGraph(EstadoAgente)

    grafo.add_node("validar_estado", validar_estado)
    grafo.add_node("finalizar", finalizar)

    grafo.add_edge(START, "validar_estado")

    grafo.add_conditional_edges(
        "validar_estado",
        lambda estado: (
            "error" if estado["errores"] else "continuar"
        ),
        {
            "error": END,
            "continuar": "finalizar",
        },
    )

    grafo.add_edge("finalizar", END)

    return grafo.compile()


app_matching = construir_grafo()