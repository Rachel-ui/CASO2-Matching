
from typing import TypedDict


class EstadoAgente(TypedDict):
    """Estado compartido entre los nodos del agente de matching."""

    vacante_actual: dict
    candidatos: list[dict]
    candidatos_filtrados: list[dict]
    resultados: list[dict]
    relajaciones_aplicadas: list[dict]
    consultas_reclutador: list[dict]
    auditoria: list[dict]
    errores: list[str]
    llm_calls: int
    requiere_revision_humana: bool
    estado: str


def crear_estado_inicial(
    vacante: dict,
    candidatos: list[dict],
) -> EstadoAgente:
    """Crea el estado inicial de una ejecución del agente."""

    return {
        "vacante_actual": vacante,
        "candidatos": candidatos,
        "candidatos_filtrados": [],
        "resultados": [],
        "relajaciones_aplicadas": [],
        "consultas_reclutador": [],
        "auditoria": [
            {
                "evento": "inicializacion",
                "detalle": "Estado inicial creado correctamente.",
            }
        ],
        "errores": [],
        "llm_calls": 0,
        "requiere_revision_humana": False,
        "estado": "inicializado",
    }