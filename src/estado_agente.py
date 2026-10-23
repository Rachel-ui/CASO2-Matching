
from typing import TypedDict


class EventoAuditoria(TypedDict, total=False):
    """Registro de una decisión tomada por un nodo del agente (RF-10)."""

    iteracion: int
    nodo: str
    decision: str
    motivo: str
    candidato_id: str


class EstadoAgente(TypedDict):
    """Estado compartido entre los nodos del agente de matching."""

    vacante_actual: dict
    candidatos: list[dict]
    duplicados: list[dict]
    candidatos_filtrados: list[dict]
    resultados: list[dict]
    shortlist: list[dict]
    configuracion: object
    relajaciones_aplicadas: list[dict]
    consultas_reclutador: list[dict]
    auditoria: list[EventoAuditoria]
    errores: list[str]
    llm_calls: int
    # Cliente del LLM (solo en modo with_llm). Se inyecta en las pruebas.
    llm: object
    requiere_revision_humana: bool
    indice_candidato: int
    iteracion: int
    proximo_indice: int
    decision_actual: str
    motivo_actual: str
    estado: str
    vacante_original: dict
    calificados: list[dict]
    evaluacion: dict


def crear_estado_inicial(
    vacante: dict,
    candidatos: list[dict],
) -> EstadoAgente:
    """Crea el estado inicial de una ejecución del agente."""

    return {
        "vacante_actual": vacante,
        "candidatos": candidatos,
        "duplicados": [],
        "candidatos_filtrados": [],
        "resultados": [],
        "shortlist": [],
        "configuracion": None,
        "relajaciones_aplicadas": [],
        "consultas_reclutador": [],
        "auditoria": [
            {
                "iteracion": 0,
                "nodo": "inicio",
                "decision": "inicializar",
                "motivo": "Se creó el estado inicial de la ejecución.",
            }
        ],
        "errores": [],
        "llm_calls": 0,
        "requiere_revision_humana": False,
        "indice_candidato": 0,
        "iteracion": 0,
        "proximo_indice": 0,
        "decision_actual": "",
        "motivo_actual": "",
        "estado": "inicializado",
        "vacante_original": dict(vacante),
        "calificados": [],
        "evaluacion": {},
    }
