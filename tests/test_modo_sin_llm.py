
import csv
import json
import time
from pathlib import Path

import pytest

from src.configuracion import (
    MODO_CON_LLM,
    MODO_SIN_LLM,
    cargar_configuracion,
    normalizar_modo,
)
from src.estado_agente import crear_estado_inicial
from src.grafo_matching import app_matching
from src.scoring import evaluar_candidato


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


def cargar_candidatos():
    with (DATA / "candidatos.csv").open("r", encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def cargar_vacantes():
    with (DATA / "vacantes.json").open("r", encoding="utf-8-sig") as archivo:
        return json.load(archivo)["vacantes"]


def ejecutar(vacante=None):
    vacante = vacante or cargar_vacantes()[0]
    return app_matching.invoke(crear_estado_inicial(vacante, cargar_candidatos()))


@pytest.fixture(autouse=True)
def modo_sin_llm(monkeypatch):
    monkeypatch.setenv("AGENTE_MODO", MODO_SIN_LLM)


# --- RNF-02: modo sin LLM ---

def test_modo_por_defecto_es_sin_llm(monkeypatch):
    monkeypatch.delenv("AGENTE_MODO", raising=False)
    assert cargar_configuracion().modo == MODO_SIN_LLM


def test_variable_de_entorno_activa_el_modo_con_llm(monkeypatch):
    monkeypatch.setenv("AGENTE_MODO", MODO_CON_LLM)
    assert cargar_configuracion().modo == MODO_CON_LLM


def test_normaliza_variantes_de_escritura():
    assert normalizar_modo("SIN_LLM") == MODO_SIN_LLM
    assert normalizar_modo("without_llm") == MODO_SIN_LLM
    assert normalizar_modo("Con-LLM") == MODO_CON_LLM
    with pytest.raises(ValueError):
        normalizar_modo("otro_modo")


def test_modo_sin_llm_no_hace_llamadas():
    resultado = ejecutar()

    assert resultado["configuracion"].sin_llm
    assert resultado["llm_calls"] == 0
    assert not resultado["errores"]
    assert resultado["estado"] == "finalizado"


def test_justificaciones_salen_de_plantilla():
    resultado = ejecutar()

    # En la primera pasada se evalúa una vez cada candidato único; si la
    # vacante necesita relajaciones, se vuelven a evaluar (RF-06).
    assert len(resultado["resultados"]) >= len(resultado["candidatos_filtrados"])
    for item in resultado["resultados"]:
        assert item["modo_justificacion"] == "plantilla"
        assert item["justificacion"].endswith(".")
        assert "Skills:" in item["justificacion"]
        assert "Experiencia:" in item["justificacion"]

    assert any(
        evento["decision"] == "without_llm"
        for evento in resultado["auditoria"]
    )


def test_la_vacante_no_necesita_parafraseo():
    # La vacante llega estructurada: se usa tal cual desde el JSON.
    vacante = cargar_vacantes()[0]
    config = cargar_configuracion()
    puntaje = evaluar_candidato(cargar_candidatos()[0], vacante, config)["puntaje"]

    assert 0 <= puntaje <= 100
    assert "descripcion" in vacante


# --- RNF-03: reproducibilidad ---

def test_dos_corridas_dan_la_misma_shortlist():
    primera = ejecutar()
    segunda = ejecutar()

    assert primera["shortlist"] == segunda["shortlist"]
    assert primera["resultados"] == segunda["resultados"]
    assert primera["auditoria"] == segunda["auditoria"]


def test_puntajes_son_reproducibles_para_toda_vacante():
    for vacante in cargar_vacantes():
        primera = ejecutar(vacante)
        segunda = ejecutar(vacante)

        assert [(i["id"], i["puntaje"]) for i in primera["shortlist"]] == [
            (i["id"], i["puntaje"]) for i in segunda["shortlist"]
        ]


def test_shortlist_esta_ordenada_por_puntaje_e_id():
    resultado = ejecutar()
    shortlist = resultado["shortlist"]

    # La shortlist tiene hasta `shortlist_size` perfiles: puede haber menos aptos.
    assert len(shortlist) <= resultado["configuracion"].shortlist_size
    claves = [(-item["puntaje"], item["id"]) for item in shortlist]
    assert claves == sorted(claves)


# --- RNF-05: rendimiento ---

def test_una_vacante_se_procesa_en_menos_de_un_minuto():
    inicio = time.perf_counter()
    resultado = ejecutar()
    duracion = time.perf_counter() - inicio

    assert resultado["estado"] == "finalizado"
    assert duracion < 60
