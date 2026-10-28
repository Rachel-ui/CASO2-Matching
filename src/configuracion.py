
"""Configuración del agente y modo de ejecución (RNF-02).

El modo se toma de la variable de entorno AGENTE_MODO. Si no existe, se usa
el valor `agent.mode` de data/config.yaml, y si tampoco está, sin_llm.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


RAIZ = Path(__file__).resolve().parent.parent
RUTA_CONFIG = RAIZ / "data" / "config.yaml"

VARIABLE_MODO = "AGENTE_MODO"
MODO_SIN_LLM = "without_llm"
MODO_CON_LLM = "with_llm"
MODOS_VALIDOS = {MODO_SIN_LLM, MODO_CON_LLM}

PESOS_POR_DEFECTO = {
    "mandatory_skills": 50,
    "desirable_skills": 20,
    "experience": 15,
    "english": 10,
    "availability": 5,
}


@dataclass(frozen=True)
class Configuracion:
    modo: str
    threshold: float
    pesos: dict[str, float]
    shortlist_size: int
    ruta: Path
    max_relajaciones: int = 3
    orden_relajacion: tuple[dict, ...] = ()
    max_consultas_reclutador: int = 3
    max_llamadas_llm: int = 30
    max_horas_monitoreo: float = 3
    max_pasos_grafo: int = 400

    @property
    def sin_llm(self) -> bool:
        return self.modo == MODO_SIN_LLM

    @property
    def recursion_limit(self) -> int:
        """Tope de ejecución de nodos que se pasa al grafo (RNF-04)."""

        return self.max_pasos_grafo

    def limites(self) -> dict:
        """Límites de la corrida, para la respuesta del agente (RNF-04)."""

        return {
            "horas_monitoreo": self.max_horas_monitoreo,
            "relajaciones": self.max_relajaciones,
            "consultas_reclutador": self.max_consultas_reclutador,
            "llamadas_llm": self.max_llamadas_llm,
            "pasos_grafo": self.max_pasos_grafo,
            "recursion_limit": self.recursion_limit,
        }


def normalizar_modo(valor: Any) -> str:
    """Acepta variantes de escritura y devuelve un modo válido."""

    modo = str(valor or "").strip().lower()

    if modo in {"without_llm", "sin_llm", "sin-llm", "sinllm"}:
        return MODO_SIN_LLM

    if modo in {"with_llm", "con_llm", "con-llm", "conllm"}:
        return MODO_CON_LLM

    raise ValueError(
        f"Modo de agente no válido: '{valor}'. "
        f"Use {MODO_SIN_LLM} o {MODO_CON_LLM}."
    )


def cargar_configuracion(ruta: Path | None = None) -> Configuracion:
    """Lee data/config.yaml y resuelve el modo de ejecución activo."""

    ruta = Path(ruta) if ruta else RUTA_CONFIG

    with ruta.open("r", encoding="utf-8-sig") as archivo:
        datos = yaml.safe_load(archivo) or {}

    scoring = datos.get("scoring", {})
    agente = datos.get("agent", {})
    pesos = dict(PESOS_POR_DEFECTO)
    pesos.update(scoring.get("weights") or {})

    modo = os.getenv(VARIABLE_MODO) or agente.get("mode") or MODO_SIN_LLM

    relajacion = datos.get("relaxation", {})
    recruiter = datos.get("recruiter", {})
    llm = datos.get("llm", {})
    limites = datos.get("limits", {})

    return Configuracion(
        modo=normalizar_modo(modo),
        threshold=float(scoring.get("threshold", 70)),
        pesos={clave: float(valor) for clave, valor in pesos.items()},
        shortlist_size=int(agente.get("shortlist_size", 3)),
        ruta=ruta,
        max_relajaciones=int(relajacion.get("max_relaxations", 3)),
        orden_relajacion=tuple(relajacion.get("order") or ()),
        max_consultas_reclutador=int(recruiter.get("max_queries", 3)),
        max_llamadas_llm=int(llm.get("max_calls_per_job", 30)),
        max_horas_monitoreo=float(limites.get("max_monitoring_hours", 3)),
        max_pasos_grafo=int(limites.get("recursion_limit", 400)),
    )
