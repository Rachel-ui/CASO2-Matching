
"""Pruebas de RNF-08: reintento y regla de respaldo cuando el LLM falla.

Un fallo del LLM se reintenta una vez; si vuelve a fallar (o devuelve un
formato inválido), se usa la regla de respaldo y el error queda en el log.
No hacen llamadas reales: el chat model se sustituye por un doble.
"""

import csv
import json
from pathlib import Path

import pytest

from src.configuracion import MODO_CON_LLM, cargar_configuracion
from src.estado_agente import crear_estado_inicial
from src.grafo_matching import app_matching
from src.llm_cliente import (
    MAX_INTENTOS_LLM,
    ErrorLLM,
    con_reintento,
    generar_justificacion_con_fallback,
    interpretar_correo_con_llm,
)


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


class LLM_Doble:
    """Responde en orden los textos dados; si es un error, lo levanta."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = 0

    def invoke(self, mensajes, **kwargs):
        self.llamadas += 1
        respuesta = self.respuestas.pop(0)

        if isinstance(respuesta, Exception):
            raise respuesta

        class _Respuesta:
            content = respuesta

        return _Respuesta()


def cargar_candidatos():
    with (DATA / "candidatos.csv").open("r", encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def cargar_vacante():
    with (DATA / "vacantes.json").open("r", encoding="utf-8-sig") as archivo:
        return json.load(archivo)["vacantes"][0]


EVALUACION = {
    "puntaje": 82,
    "cumple_requisitos": True,
    "motivo": "Justificación por plantilla.",
    "detalle": {
        "cumplidos": ["Python"],
        "faltantes": [],
        "deseables_cumplidos": [],
        "experiencia": 5,
        "experiencia_requerida": 3,
        "nivel_candidato": "B2",
        "nivel_requerido": "B1",
        "fecha_candidato": "2026-10-01",
        "fecha_requerida": "2026-11-01",
        "modalidad_candidato": "remoto",
        "modalidad_vacante": "remoto",
    },
}


def test_con_reintento_reintenta_una_vez_y_devuelve_el_resultado():
    llm = LLM_Doble([RuntimeError("sin red"), "texto válido"])

    resultado = con_reintento(lambda: llm.invoke([("user", "hola")]))

    assert llm.llamadas == MAX_INTENTOS_LLM
    assert resultado.content == "texto válido"


def test_con_reintento_relanza_el_error_y_lo_deja_para_el_log():
    llm = LLM_Doble([RuntimeError("sin red"), ErrorLLM("formato inválido")])

    with pytest.raises(ErrorLLM) as error:
        con_reintento(lambda: llm.invoke([]))

    assert llm.llamadas == MAX_INTENTOS_LLM
    assert "2 intento" in str(error.value)


def test_si_el_llm_falla_dos_veces_se_usa_la_plantilla():
    llm = LLM_Doble([RuntimeError("sin red"), RuntimeError("sin red")])

    texto, fuente, error = generar_justificacion_con_fallback(
        llm, {"id": "C001"}, {"titulo": "Vacante"}, EVALUACION
    )

    assert fuente == "plantilla"
    assert texto == EVALUACION["motivo"]
    assert "sin red" in error
    assert llm.llamadas == 2


def test_un_reintento_exitoso_no_cae_a_la_plantilla():
    llm = LLM_Doble([RuntimeError("red intermitente"), "Justificación del LLM."])

    texto, fuente, error = generar_justificacion_con_fallback(
        llm, {"id": "C001"}, {"titulo": "Vacante"}, EVALUACION
    )

    assert (texto, fuente, error) == ("Justificación del LLM.", "llm", "")


def test_clasificacion_con_formato_invalido_reintenta_y_cae_a_las_reglas():
    llm = LLM_Doble(["esto no es JSON", '{"clase": "cualquier_cosa"}'])
    correo = {"asunto": "Vacante", "cuerpo": "Buscamos desarrollador Python."}

    with pytest.raises(ErrorLLM):
        interpretar_correo_con_llm(llm, correo)

    assert llm.llamadas == MAX_INTENTOS_LLM


def test_clasificacion_se_recupera_en_el_reintento():
    respuesta = json.dumps(
        {"clase": "no_relacionado", "motivo": "Es una factura", "tipo_texto": "factura"}
    )
    llm = LLM_Doble(["sin formato", respuesta])

    datos = interpretar_correo_con_llm(llm, {"asunto": "Factura", "cuerpo": "Total: 100"})

    assert datos["clase"] == "no_relacionado"
    assert llm.llamadas == 2


@pytest.fixture
def modo_con_llm(monkeypatch):
    monkeypatch.setenv("AGENTE_MODO", MODO_CON_LLM)


def test_en_el_grafo_el_fallback_queda_en_el_log(modo_con_llm):
    doble = LLM_Doble([RuntimeError("cuota"), RuntimeError("cuota")])
    estado = {
        **crear_estado_inicial(cargar_vacante(), cargar_candidatos()),
        "llm": doble,
    }

    resultado = app_matching.invoke(estado)

    assert resultado["resultados"][0]["modo_justificacion"] == "plantilla"
    eventos = [e for e in resultado["auditoria"] if e["decision"] == "fallback_plantilla"]
    assert eventos, "RNF-08 exige que el error del LLM quede en el log"
    assert any("LLM" in error for error in resultado["errores"])
    # Dos intentos por perfil, limitados por `llm.max_calls_per_job`.
    assert doble.llamadas <= cargar_configuracion().max_llamadas_llm
