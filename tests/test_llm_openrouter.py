
"""Pruebas del modo con LLM por OpenRouter (RNF-01).

No hacen llamadas reales: el chat model se sustituye por un doble que
devuelve texto fijo, así no se consume cuota ni se necesita la clave.
"""

import csv
import json
from pathlib import Path

import pytest

from src.configuracion import MODO_CON_LLM, cargar_configuracion
from src.estado_agente import crear_estado_inicial
from src.grafo_matching import app_matching
from src.llm_cliente import (
    MODELO_POR_DEFECTO,
    PROMPT_SISTEMA,
    ErrorLLM,
    api_key_configurada,
    crear_llm,
    generar_justificacion,
    modelo_actual,
)


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


def cargar_candidatos():
    with (DATA / "candidatos.csv").open("r", encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def cargar_vacante():
    with (DATA / "vacantes.json").open("r", encoding="utf-8-sig") as archivo:
        return json.load(archivo)["vacantes"][0]


class LLM_Doble:
    """Sustituto del chat model: guarda los mensajes y responde un texto fijo."""

    def __init__(self, texto="Justificación generada por el LLM.", error=None):
        self.texto = texto
        self.error = error
        self.mensajes = []

    def invoke(self, mensajes):
        self.mensajes.append(mensajes)
        if self.error:
            raise self.error

        class Respuesta:
            content = self.texto

        return Respuesta()


# --- RNF-01: dependencias y OpenRouter ---

def test_modelo_por_defecto_es_de_anthropic():
    assert MODELO_POR_DEFECTO.startswith("anthropic/")


def test_modelo_se_puede_cambiar_por_variable(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4")
    assert modelo_actual() == "anthropic/claude-sonnet-4"


def test_sin_api_key_falla_con_mensaje_claro(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("src.llm_cliente.RUTA_ENV", tmp_path / "no-existe.env")

    with pytest.raises(ErrorLLM, match="OPENROUTER_API_KEY"):
        crear_llm()


def test_cliente_apunta_a_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "clave-de-prueba")

    llm = crear_llm()

    assert str(llm.openai_api_base).rstrip("/") == "https://openrouter.ai/api/v1"
    assert llm.model_name == modelo_actual()
    assert llm.temperature == 0


def test_api_key_desde_env_o_archivo(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    archivo = tmp_path / ".env"
    archivo.write_text("OPENROUTER_API_KEY=sk-or-v1-prueba\n", encoding="utf-8")

    assert api_key_configurada(archivo)
    assert not api_key_configurada(tmp_path / "vacio.env")


def test_requisitos_tienen_versiones_fijadas():
    lineas = [
        linea.strip()
        for linea in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]

    assert lineas, "requirements.txt está vacío"
    assert all("==" in linea for linea in lineas)


def test_requisitos_incluyen_el_cliente_de_openrouter():
    contenido = (RAIZ / "requirements.txt").read_text(encoding="utf-8")

    assert "langchain-openai" in contenido


# --- RNF-02: el LLM solo redacta, nunca puntúa ---

def test_prompt_prohibe_usar_datos_personales():
    assert "género" in PROMPT_SISTEMA
    assert "No inventes datos" in PROMPT_SISTEMA


def test_justificacion_no_cambia_el_puntaje():
    evaluacion = {
        "puntaje": 73.5,
        "cumple_requisitos": True,
        "detalle": {
            "cumplidos": ["Python"],
            "faltantes": [],
            "deseables_cumplidos": [],
            "experiencia": 3,
            "experiencia_requerida": 3,
            "nivel_candidato": "B2",
            "nivel_requerido": "B1",
            "fecha_candidato": "2026-10-20",
            "fecha_requerida": "2026-11-01",
            "modalidad_candidato": "remoto",
            "modalidad_vacante": "remoto",
        },
    }
    doble = LLM_Doble()

    texto = generar_justificacion(doble, {"id": "C001"}, {"titulo": "Vacante"}, evaluacion)

    assert texto == "Justificación generada por el LLM."
    assert "73.5" in doble.mensajes[0][1][1]
    # El nombre del candidato no se envía al modelo.
    assert "C001" not in doble.mensajes[0][1][1]


def test_respuesta_vacia_del_llm_es_un_error():
    evaluacion = {
        "puntaje": 0,
        "cumple_requisitos": False,
        "detalle": {
            "cumplidos": [], "faltantes": [], "deseables_cumplidos": [],
            "experiencia": 0, "experiencia_requerida": 0,
            "nivel_candidato": "", "nivel_requerido": "",
            "fecha_candidato": "", "fecha_requerida": "",
            "modalidad_candidato": "", "modalidad_vacante": "",
        },
    }

    with pytest.raises(ErrorLLM, match="vacía"):
        generar_justificacion(LLM_Doble(texto="  "), {}, {}, evaluacion)


# --- Modo con LLM dentro del grafo ---

@pytest.fixture
def modo_con_llm(monkeypatch):
    monkeypatch.setenv("AGENTE_MODO", MODO_CON_LLM)


def test_grafo_usa_el_llm_para_justificar(modo_con_llm):
    doble = LLM_Doble()
    estado = {**crear_estado_inicial(cargar_vacante(), cargar_candidatos()), "llm": doble}

    resultado = app_matching.invoke(estado)

    assert resultado["llm_calls"] > 0
    assert resultado["resultados"][0]["modo_justificacion"] == "llm"
    assert resultado["resultados"][0]["justificacion"] == doble.texto


def test_si_el_llm_falla_se_usa_la_plantilla(modo_con_llm):
    doble = LLM_Doble(error=RuntimeError("sin red"))
    estado = {**crear_estado_inicial(cargar_vacante(), cargar_candidatos()), "llm": doble}

    resultado = app_matching.invoke(estado)

    assert resultado["resultados"][0]["modo_justificacion"] == "plantilla"
    assert "Skills:" in resultado["resultados"][0]["justificacion"]
    assert any("LLM" in error for error in resultado["errores"])


def test_las_llamadas_al_llm_se_limitan(monkeypatch):
    monkeypatch.setenv("AGENTE_MODO", MODO_CON_LLM)
    monkeypatch.setattr(
        "src.grafo_matching.cargar_configuracion",
        lambda *a, **k: _config_limitada(),
    )
    doble = LLM_Doble()
    estado = {**crear_estado_inicial(cargar_vacante(), cargar_candidatos()), "llm": doble}

    resultado = app_matching.invoke(estado)

    assert resultado["configuracion"].modo == MODO_CON_LLM
    assert resultado["llm_calls"] == 2
    assert len(doble.mensajes) == 2
    # Tras agotar la cuota, los demás perfiles se justifican con plantilla.
    assert any(
        item["modo_justificacion"] == "plantilla" for item in resultado["resultados"]
    )


def _config_limitada():

    from src.configuracion import Configuracion, MODO_CON_LLM, PESOS_POR_DEFECTO
    from pathlib import Path


    return Configuracion(
        modo=MODO_CON_LLM,
        threshold=70.0,
        pesos=dict(PESOS_POR_DEFECTO),
        shortlist_size=3,
        ruta=Path("data/config.yaml"),
        max_relajaciones=3,
        orden_relajacion=(),
        max_consultas_reclutador=3,
        max_llamadas_llm=2,
    )
