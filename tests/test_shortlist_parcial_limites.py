
"""Pruebas de RF-07 (shortlist parcial con explicación) y RNF-04 (límites).

RF-07: si tras las relajaciones no hay 3 candidatos, se entregan los que
tenga la shortlist y se explica qué requisito impide completarla.
RNF-04: tope de relajaciones, consultas al reclutador, llamadas al LLM,
horas simuladas de monitoreo y `recursion_limit` del grafo.
"""

import csv
import json
from pathlib import Path

import pytest

from src.configuracion import MODO_SIN_LLM, cargar_configuracion
from src.estado_agente import crear_estado_inicial
from src.ejecutar_matching import resumen_resultado
from src.grafo_matching import app_matching
from src.scoring import explicar_shortlist_incompleta


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


def cargar_vacantes():
    with (DATA / "vacantes.json").open("r", encoding="utf-8-sig") as archivo:
        return json.load(archivo)["vacantes"]


def cargar_candidatos():
    with (DATA / "candidatos.csv").open("r", encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def ejecutar(vacante):
    return app_matching.invoke(
        crear_estado_inicial(vacante, cargar_candidatos()),
        {"recursion_limit": 1000, "max_concurrency": 1},
    )


@pytest.fixture(autouse=True)
def modo_sin_llm(monkeypatch):
    monkeypatch.setenv("AGENTE_MODO", MODO_SIN_LLM)


def vacante_dificil(**cambios):
    vacante = dict(cargar_vacantes()[2])
    vacante.update(cambios)
    return vacante


# --- RF-07 ---

def test_vacante_imposible_entrega_shortlist_parcial_y_explica():
    resultado = ejecutar(vacante_dificil())

    assert resultado["estado"] == "incompleta"
    assert resultado["requiere_revision_humana"] is True

    analisis = resultado["analisis_shortlist"]
    assert analisis["puestos_libres"] > 0
    # La shortlist se entrega tal como quedó (vacía o parcial), no se inventa.
    assert analisis["puestos_llenos"] == len(resultado["shortlist"])
    assert "skills_obligatorios" in analisis["requisito_principal"]
    assert analisis["motivo_principal"]
    assert any(bloque["requisito"] == "skills_obligatorios" for bloque in analisis["bloqueantes"])


def test_la_explicacion_sale_en_la_auditoria_de_finalizar():
    resultado = ejecutar(vacante_dificil())

    motivo = [
        evento["motivo"] for evento in resultado["auditoria"] if evento["nodo"] == "finalizar"
    ][-1]

    assert "shortlist" in motivo.lower()
    assert "skills obligatorios" in motivo.lower()


def test_bloqueantes_nombran_los_candidatos_y_el_requisito():
    resultado = ejecutar(vacante_dificil())
    bloque = next(
        b for b in resultado["analisis_shortlist"]["bloqueantes"]
        if b["requisito"] == "skills_obligatorios"
    )

    assert bloque["casos"]
    assert "le faltan" in bloque["casos"][0]


def test_sin_perfiles_no_hay_bloqueantes():
    config = cargar_configuracion()
    analisis = explicar_shortlist_incompleta([], cargar_vacantes()[2], [], config)

    assert analisis["puestos_libres"] == config.shortlist_size
    assert analisis["bloqueantes"] == []
    assert "perfiles únicos" in analisis["motivo_principal"]


def test_vacante_completa_no_tiene_puestos_libres():
    resultado = ejecutar(cargar_vacantes()[0])

    assert resultado["analisis_shortlist"]["puestos_libres"] == 0
    assert len(resultado["shortlist"]) == 3

    resumen = resumen_resultado(resultado)
    assert resumen["shortlist_parcial"] is False
    assert resumen["requisito_bloqueante"] == ""
    assert resumen["motivo_incompleta"] == ""
    assert resumen["bloqueantes"] == []


# --- RNF-04 ---

def test_limites_configurados():
    config = cargar_configuracion()

    assert config.max_relajaciones == 3
    assert config.max_consultas_reclutador == 3
    assert config.max_llamadas_llm == 30
    assert config.recursion_limit == config.max_pasos_grafo


def test_nunca_pasa_de_tres_relajaciones():
    resultado = ejecutar(cargar_vacantes()[2])

    assert len(resultado["relajaciones_aplicadas"]) <= 3


def test_nunca_pasa_de_tres_consultas_respondidas():
    resultado = ejecutar(cargar_vacantes()[2])

    respondidas = [
        consulta for consulta in resultado["consultas_reclutador"]
        if consulta["resultado"] == "respondida"
    ]
    assert len(respondidas) <= 3


def test_monitoreo_no_pasa_de_24_horas_simuladas():
    from src.leer_correos import HORAS_SIMULADAS_POR_CORRIDA, ventana_simulada

    config = cargar_configuracion()

    assert ventana_simulada(config) <= 24
    assert ventana_simulada(config) == (
        config.max_horas_monitoreo * HORAS_SIMULADAS_POR_CORRIDA
    )
    assert HORAS_SIMULADAS_POR_CORRIDA * 3 == 24


def test_los_limites_quedan_en_el_estado():
    resultado = ejecutar(cargar_vacantes()[0])

    assert resultado["limites"]["relajaciones"] == 3
    assert resultado["limites"]["consultas_reclutador"] == 3
    assert resultado["limites"]["llamadas_llm"] == 30
    assert resultado["limites"]["horas_monitoreo"] > 0
    assert resultado["limites"]["recursion_limit"] == resultado["configuracion"].recursion_limit
    assert 0 < resultado["pasos_grafo"] <= resultado["configuracion"].recursion_limit


def test_el_recursion_limit_corta_la_corrida():
    # Un tope de 5 pasos no alcanza ni para llegar a la shortlist.
    estado = crear_estado_inicial(cargar_vacantes()[0], cargar_candidatos())

    with pytest.raises(RecursionError):
        app_matching.invoke(estado, {"recursion_limit": 5, "max_concurrency": 1})


def test_invocar_con_limite_corta_si_no_cabe():
    from src.ejecutar_matching import invocar_con_limite

    # Con el máximo configurado en 5 pasos, LangGraph corta con RecursionError.
    estado = crear_estado_inicial(cargar_vacantes()[0], cargar_candidatos())

    with pytest.raises(RecursionError):
        invocar_con_limite(estado, _config_con_pocos_pasos())


def _config_con_pocos_pasos():
    from pathlib import Path

    from src.configuracion import PESOS_POR_DEFECTO, Configuracion

    return Configuracion(
        modo=MODO_SIN_LLM,
        threshold=70.0,
        pesos=dict(PESOS_POR_DEFECTO),
        shortlist_size=3,
        ruta=Path("data/config.yaml"),
        max_pasos_grafo=5,
    )
