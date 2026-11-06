
"""Pruebas de RF-08 (aprobación humana con interrupt y reemplazo).

El grafo con checkpointer se pausa en `aprobacion_humana` y espera
`Command(resume=...)`, igual que en `python -m src.aprobacion`.
"""

import csv
import json
from pathlib import Path

import pytest
from langgraph.types import Command

from src.configuracion import MODO_SIN_LLM
from src.estado_agente import crear_estado_inicial
from src.grafo_matching import (
    app_matching,
    compilar_con_aprobacion,
    interpretar_respuesta_humana,
)


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


@pytest.fixture(autouse=True)
def modo_sin_llm(monkeypatch):
    monkeypatch.setenv("AGENTE_MODO", MODO_SIN_LLM)


def cargar_candidatos():
    with (DATA / "candidatos.csv").open("r", encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def cargar_vacante():
    with (DATA / "vacantes.json").open("r", encoding="utf-8-sig") as archivo:
        return json.load(archivo)["vacantes"][0]


def contenido_interrupt(resultado):
    return [i.value for i in resultado.get("__interrupt__", ())]


# --- interpretación de la respuesta humana ---

def test_respuesta_vacia_aprueba_todo():
    shortlist = [{"id": "C001"}, {"id": "C002"}]

    assert interpretar_respuesta_humana(None, shortlist) == []
    assert interpretar_respuesta_humana({}, shortlist) == []


def test_acepta_lista_dict_y_clave_rechazar():
    shortlist = [{"id": "C001"}, {"id": "C002"}, {"id": "C003"}]

    assert interpretar_respuesta_humana(["C002"], shortlist) == ["C002"]
    assert interpretar_respuesta_humana({"C001": "rechazar"}, shortlist) == ["C001"]
    assert interpretar_respuesta_humana({"rechazar": ["C003"]}, shortlist) == ["C003"]
    # Un ID que no está en la shortlist no se toma como rechazo.
    assert interpretar_respuesta_humana(["C999"], shortlist) == []


# --- interrupt dentro del grafo ---

def test_el_grafo_se_detiene_con_la_shortlist_para_aprobar():
    grafo = compilar_con_aprobacion()
    hilo = {"configurable": {"thread_id": "test-aprobacion-1"}}

    estado = crear_estado_inicial(cargar_vacante(), cargar_candidatos())
    estado["interrupt_habilitado"] = True
    resultado = grafo.invoke(estado, hilo)
    pendientes = contenido_interrupt(resultado)

    assert pendientes, "el grafo debía detenerse en el interrupt de RF-08"
    payload = pendientes[0]
    assert payload["tipo"] == "aprobacion_shortlist"
    assert payload["shortlist"], "la shortlist a aprobar no puede estar vacía"
    assert grafo.get_state(hilo).next == ("aprobacion_humana",)


def test_aprobar_la_shortlist_cierra_la_corrida():
    grafo = compilar_con_aprobacion()
    hilo = {"configurable": {"thread_id": "test-aprobacion-2"}}
    estado = crear_estado_inicial(cargar_vacante(), cargar_candidatos())
    estado["interrupt_habilitado"] = True
    resultado = grafo.invoke(estado, hilo)
    ofrecidos = [item["id"] for item in contenido_interrupt(resultado)[0]["shortlist"]]

    resultado = grafo.invoke(Command(resume=[]), hilo)

    assert resultado["aprobacion"]["estado"] == "aprobada"
    assert resultado["aprobacion"]["aprobados"] == ofrecidos
    assert resultado["estado"] == "finalizado"
    assert any(
        evento["decision"] == "shortlist_aprobada" for evento in resultado["auditoria"]
    )


def test_rechazar_excluye_y_pide_aprobacion_del_reemplazo():
    grafo = compilar_con_aprobacion()
    hilo = {"configurable": {"thread_id": "test-aprobacion-3"}}
    estado = crear_estado_inicial(cargar_vacante(), cargar_candidatos())
    estado["interrupt_habilitado"] = True
    resultado = grafo.invoke(estado, hilo)
    original = [item["id"] for item in contenido_interrupt(resultado)[0]["shortlist"]]

    resultado = grafo.invoke(Command(resume={"rechazar": original[:1]}), hilo)
    pendientes = contenido_interrupt(resultado)
    ids_shortlist = {item["id"] for item in resultado["shortlist"]}

    # El rechazado sale de la shortlist y el flujo vuelve a pedir aprobación.
    assert original[0] not in ids_shortlist
    assert original[0] in resultado["candidatos_rechazados"]
    assert pendientes, "con rechazos el grafo debe volver al interrupt"

    resultado = grafo.invoke(Command(resume=[]), hilo)

    rechazados = resultado["aprobacion"]["rechazados"]
    assert rechazados == [original[0]]
    reemplazados = [
        item for item in resultado["shortlist"] if item.get("reemplaza_a") == original[0]
    ]
    assert len(reemplazados) <= 1
    # Si había un perfil apto libre, se usó como reemplazo.
    assert any(
        evento["decision"] in ("reemplazo_encontrado", "sin_reemplazo")
        for evento in resultado["auditoria"]
    )


def test_la_corrida_automatica_no_se_detiene_y_aprueba_la_shortlist():
    resultado = app_matching.invoke(crear_estado_inicial(cargar_vacante(), cargar_candidatos()))

    assert resultado["estado"] != "en_aprobacion"
    assert resultado["aprobacion"], "RF-08 debe dejar constancia de la aprobación"
    assert resultado["aprobacion"]["estado"] in (
        "aprobada",
        "aprobada_por_limite",
        "sin_shortlist",
    )
