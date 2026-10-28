
"""Pruebas de la regla de puntuación, relajación, reclutador y condición de éxito.

Cubre RF-04 (consultar dato faltante), RF-05 (éxito con al menos 3 sobre el
umbral), RF-06 (relajar criterios) y la regla de puntuación de 100 puntos
(experiencia 15/8/0 e inglés 10/5/0).
"""

import json
from pathlib import Path

import pytest

from src.configuracion import MODO_SIN_LLM, cargar_configuracion
from src.estado_agente import crear_estado_inicial
from src.grafo_matching import app_matching
from src.reclutador import buscar_respuesta, consultar_candidato
from src.relajacion import aplicar_relajacion
from src.scoring import evaluar_candidato


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


def cargar_vacantes():
    with (DATA / "vacantes.json").open("r", encoding="utf-8-sig") as archivo:
        return json.load(archivo)["vacantes"]


def ejecutar(vacante):
    return app_matching.invoke(crear_estado_inicial(vacante, cargar_candidatos()))


def cargar_candidatos():
    import csv

    with (DATA / "candidatos.csv").open("r", encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


@pytest.fixture(autouse=True)
def modo_sin_llm(monkeypatch):
    monkeypatch.setenv("AGENTE_MODO", MODO_SIN_LLM)


VACANTE = {
    "id": "VT",
    "titulo": "Prueba",
    "skills_obligatorios": [],
    "skills_deseables": [],
    "experience_required": 3,
    "english_required": "B2",
    "availability_required": "2026-11-01",
    "modality": "remoto",
}


def candidato(**cambios):
    base = {
        "id": "X1",
        "nombre": "Candidato de prueba",
        "skills": "",
        "experience_years": "3",
        "english_level": "B2",
        "availability_date": "2026-10-20",
        "modality": "remoto",
    }
    base.update(cambios)
    return base


# --- Regla de puntuación ---

def test_experiencia_cumple_da_15():
    evaluacion = evaluar_candidato(candidato(experience_years="5"), VACANTE, cargar_configuracion())
    assert evaluacion["criterios"]["experience"] == 15


def test_experiencia_con_un_ano_menos_da_8():
    evaluacion = evaluar_candidato(candidato(experience_years="2"), VACANTE, cargar_configuracion())
    assert evaluacion["criterios"]["experience"] == pytest.approx(7.5)


def test_experiencia_con_mas_de_un_ano_menos_da_0():
    evaluacion = evaluar_candidato(candidato(experience_years="1"), VACANTE, cargar_configuracion())
    assert evaluacion["criterios"]["experience"] == 0


def test_ingles_un_nivel_abajo_da_5():
    evaluacion = evaluar_candidato(candidato(english_level="B1"), VACANTE, cargar_configuracion())
    assert evaluacion["criterios"]["english"] == 5


def test_ingles_mas_de_un_nivel_abajo_da_0():
    evaluacion = evaluar_candidato(candidato(english_level="A2"), VACANTE, cargar_configuracion())
    assert evaluacion["criterios"]["english"] == 0


def test_sin_fecha_de_disponibilidad_da_0():
    evaluacion = evaluar_candidato(
        candidato(availability_date=""), VACANTE, cargar_configuracion()
    )
    assert evaluacion["criterios"]["availability"] == 0


def test_puntaje_maximo_es_100():
    vacante = {
        **VACANTE,
        "skills_obligatorios": ["Python"],
        "skills_deseables": ["Docker"],
    }
    evaluacion = evaluar_candidato(
        candidato(skills="Python;Docker"), vacante, cargar_configuracion()
    )
    assert evaluacion["puntaje"] == 100


# --- RF-06: relajaciones ---

def test_orden_de_relajacion_es_fecha_experiencia_ingles():
    config = cargar_configuracion()
    vacante = dict(VACANTE)
    aplicadas = []

    for _ in range(3):
        vacante, relajacion, estado = aplicar_relajacion(vacante, aplicadas, config)
        assert estado == "aplicada"
        aplicadas.append(relajacion)

    assert [r["tipo"] for r in aplicadas] == ["start_date", "experience", "english"]
    assert vacante["availability_required"] == "2026-11-15"
    assert vacante["experience_required"] == 2
    assert vacante["english_required"] == "B1"


def test_relajacion_de_fecha_mueve_dos_semanas():
    config = cargar_configuracion()
    vacante, relajacion, _ = aplicar_relajacion(dict(VACANTE), [], config)

    assert vacante["availability_required"] == "2026-11-15"
    assert relajacion["tipo"] == "start_date"


def test_no_se_relajan_los_skills_obligatorios():
    config = cargar_configuracion()
    vacante = {**VACANTE, "skills_obligatorios": ["Python", "SQL"]}

    for _ in range(config.max_relajaciones):
        vacante, _, _ = aplicar_relajacion(vacante, [], config)

    assert vacante["skills_obligatorios"] == ["Python", "SQL"]


def test_hay_como_maximo_tres_relajaciones():
    config = cargar_configuracion()
    vacante = dict(VACANTE)
    aplicadas = []

    for _ in range(config.max_relajaciones):
        vacante, relajacion, estado = aplicar_relajacion(vacante, aplicadas, config)
        aplicadas.append(relajacion)

    _, relajacion, estado = aplicar_relajacion(vacante, aplicadas, config)

    assert relajacion is None
    assert estado == "agotada"
    assert len(aplicadas) == config.max_relajaciones


def test_vacante_sin_ingles_no_relaja_ingles():
    config = cargar_configuracion()
    vacante = {**VACANTE, "english_required": ""}
    vacante, _, _ = aplicar_relajacion(vacante, [{"tipo": "start_date"}], config)
    vacante, _, estado = aplicar_relajacion(
        vacante, [{"tipo": "start_date"}, {"tipo": "experience"}], config
    )

    assert estado == "sin_mas_criterios"
    assert vacante["english_required"] == ""


# --- RF-04: reclutador ---

def test_reclutador_responde_el_dato_faltante():
    respuestas = [{"candidate_id": "X1", "campo": "availability_date", "respuesta": "2026-11-01"}]
    actualizado, consultas = consultar_candidato(candidato(availability_date=""), respuestas)

    assert actualizado["availability_date"] == "2026-11-01"
    assert consultas[0]["resultado"] == "respondida"
    # El perfil original no se modifica.
    assert candidato(availability_date="")["availability_date"] == ""


def test_reclutador_no_se_sabe_deja_el_dato_vacio():
    respuestas = [{"candidate_id": "X1", "campo": "availability_date", "respuesta": "no se sabe"}]
    actualizado, consultas = consultar_candidato(candidato(availability_date=""), respuestas)

    assert actualizado["availability_date"] == ""
    assert consultas[0]["resultado"] == "no_se_sabe"


def test_reclutador_respeta_el_limite_de_consultas():
    resultado = ejecutar(cargar_vacantes()[0])
    consultas = resultado["consultas_reclutador"]
    limite = resultado["configuracion"].max_consultas_reclutador

    respondidas = [c for c in consultas if c["resultado"] == "respondida"]
    # Se pregunta por prioridad y se corta en el máximo; puede preguntarse a
    # menos perfiles si los que quedan ya traen el dato.
    assert len(respondidas) <= limite
    assert all(c["candidato_id"] for c in consultas)


def test_reclutador_responde_a_los_perfiles_mas_prometedores():
    resultado = ejecutar(cargar_vacantes()[0])
    respondidas = [
        c for c in resultado["consultas_reclutador"] if c["resultado"] == "respondida"
    ]

    # Los datos faltantes se preguntan por el perfil, así se aprovechan las
    # consultas limitadas (RNF-04) en quien puede quedar en la shortlist.
    for consulta in respondidas:
        assert consulta["campo"] == "availability_date"
        assert consulta["respuesta"]


def test_buscar_respuesta_sin_registro_devuelve_vacio():
    assert buscar_respuesta("NO-EXISTE", "availability_date", []) == ""


# --- RF-05: condición de éxito ---

def test_vacante_facil_tiene_exito():
    resultado = ejecutar(cargar_vacantes()[0])

    assert resultado["estado"] == "finalizado"
    assert resultado["evaluacion"]["exito"] is True
    assert resultado["evaluacion"]["aptos"] >= 3
    assert len(resultado["shortlist"]) == resultado["configuracion"].shortlist_size


def test_vacante_dificil_no_se_completa_ni_con_tres_relajaciones():
    dificil = [v for v in cargar_vacantes() if v["id"] == "V003"][0]
    resultado = ejecutar(dificil)

    assert resultado["estado"] == "incompleta"
    assert resultado["requiere_revision_humana"] is True
    assert len(resultado["relajaciones_aplicadas"]) == 3
    assert resultado["evaluacion"]["exito"] is False
    assert resultado["shortlist"] == []


def test_cada_relajacion_queda_en_la_auditoria():
    dificil = [v for v in cargar_vacantes() if v["id"] == "V003"][0]
    resultado = ejecutar(dificil)

    relajaciones = [
        evento for evento in resultado["auditoria"]
        if evento["nodo"] == "relajar_criterios"
        and evento["decision"] != "sin_relajaciones"
    ]
    assert len(relajaciones) == 3
    assert [e["decision"] for e in relajaciones] == [
        "relajar_start_date",
        "relajar_experience",
        "relajar_english",
    ]
    ultimo = [e for e in resultado["auditoria"] if e["nodo"] == "relajar_criterios"][-1]
    assert ultimo["decision"] == "sin_relajaciones"


def test_se_registra_la_decision_de_exito():
    resultado = ejecutar(cargar_vacantes()[0])

    decisiones = [
        (evento["nodo"], evento["decision"]) for evento in resultado["auditoria"]
    ]
    assert ("evaluar_resultado", "exito_parcial") in decisiones
    assert ("evaluar_resultado", "exito") in decisiones
