"""Pruebas de RF-11: el reporte por vacante.

El reporte tiene que traer, para cada vacante:

- la shortlist con puntaje y justificación;
- el puntaje desglosado de cada candidato, y que la suma de los componentes
  sea el puntaje total;
- los criterios que se relajaron, con su valor anterior y el nuevo;
- los supuestos con los que se trabajó;
- y, si la vacante quedó incompleta, qué lo impide (RF-07).

Se generan en un directorio temporal: las pruebas no ensucian `reports/`.
"""

import csv
import json
from pathlib import Path

import pytest

from src.configuracion import cargar_configuracion
from src.ejecutar_matching import ejecutar_vacante
from src.reporte_vacante import (
    COMPONENTES,
    construir_reporte,
    generar_reporte,
    renderizar_markdown,
)


@pytest.fixture(scope="module")
def config():
    return cargar_configuracion()


@pytest.fixture(scope="module")
def resultado_v001():
    return ejecutar_vacante("V001")


@pytest.fixture(scope="module")
def resultado_v003():
    return ejecutar_vacante("V003")


@pytest.fixture(scope="module")
def reporte_v001(resultado_v001, config):
    return construir_reporte(resultado_v001, config)


@pytest.fixture(scope="module")
def reporte_v003(resultado_v003, config):
    return construir_reporte(resultado_v003, config)


# --- shortlist ---

def test_el_reporte_trae_la_shortlist(reporte_v001):
    assert reporte_v001["shortlist"]
    for item in reporte_v001["shortlist"]:
        assert item["id"]
        assert item["puntaje"] >= reporte_v001["configuracion"]["umbral"]
        assert item["justificacion"]


def test_la_shortlist_coincide_con_los_puestos_del_matching(reporte_v001):
    puestos = [item["posicion"] for item in reporte_v001["shortlist"]]

    assert puestos == list(range(1, len(puestos) + 1))


# --- puntaje desglosado ---

def test_cada_candidato_tiene_los_cinco_componentes(reporte_v001):
    claves = {clave for clave, _ in COMPONENTES}

    for candidato in reporte_v001["candidatos"]:
        assert {componente["componente"] for componente in candidato["componentes"]} == claves


def test_la_suma_de_componentes_es_el_puntaje(reporte_v001):
    for candidato in reporte_v001["candidatos"]:
        suma = sum(componente["puntos"] for componente in candidato["componentes"])
        assert abs(suma - candidato["puntaje_absoluto"]) < 0.05, candidato["id"]


def test_los_componentes_no_pasan_su_maximo(reporte_v001):
    for candidato in reporte_v001["candidatos"]:
        for componente in candidato["componentes"]:
            assert 0 <= componente["puntos"] <= componente["maximo"]
            assert componente["valor"]


def test_se_evaluan_todos_los_candidatos_unicos(reporte_v001, resultado_v001):
    assert len(reporte_v001["candidatos"]) == len(resultado_v001["candidatos_filtrados"])


def test_el_reporte_marca_quien_quedo_fuera_y_por_que(reporte_v001):
    fuera = [c for c in reporte_v001["candidatos"] if not c["en_shortlist"]]

    assert fuera
    # Quien supera el umbral y cumple los requisitos puede quedar fuera solo
    # si la shortlist ya estaba llena: el reporte lo deja visible en vez de
    # esconderlo.
    llenos = reporte_v001["configuracion"]["shortlist_size"]
    for candidato in fuera:
        apto = candidato["cumple_requisitos"] and candidato["puntaje_absoluto"] >= 70
        assert not apto or llenos == len(reporte_v001["shortlist"])
    assert all(c["posicion"] is None for c in fuera)


def test_el_reporte_dice_que_componente_descuenta_mas(reporte_v001):
    perdidas = reporte_v001["puntos_perdidos_por_componente"]

    assert perdidas
    assert set(perdidas) <= {etiqueta for _, etiqueta in COMPONENTES}


# --- relajaciones ---

def test_las_relajaciones_van_con_antes_y_despues(reporte_v001):
    assert reporte_v001["criterios_relajados"]
    for relajacion in reporte_v001["criterios_relajados"]:
        assert relajacion["antes"] != relajacion["despues"]
        assert relajacion["descripcion"]


def test_la_vacante_dificil_relaja_los_tres_criterios(reporte_v003):
    tipos = [relajacion["tipo"] for relajacion in reporte_v003["criterios_relajados"]]

    assert tipos == ["start_date", "experience", "english"]


def test_los_skills_obligatorios_nunca_aparecen_relajados(reporte_v003):
    for relajacion in reporte_v003["criterios_relajados"]:
        assert "skills" not in relajacion["tipo"]

    original = reporte_v003["criterios_originales"]["skills_obligatorios"]
    vigente = reporte_v003["criterios_vigentes"]["skills_obligatorios"]
    assert original == vigente


def test_los_criterios_originales_no_se_pisan(reporte_v001):
    original = reporte_v001["criterios_originales"]["availability_required"]
    vigente = reporte_v001["criterios_vigentes"]["availability_required"]

    assert original == "2026-10-25"
    assert vigente != original


# --- supuestos ---

def test_el_reporte_lista_los_supuestos(reporte_v001):
    temas = " ".join(supuesto["tema"] for supuesto in reporte_v001["supuestos"])

    assert "Umbral" in temas
    assert "Pesos" in temas
    assert "Skills obligatorios" in temas
    assert "relajación" in temas
    for supuesto in reporte_v001["supuestos"]:
        assert supuesto["supuesto"]
        assert supuesto["fuente"]


def test_el_supuesto_del_umbral_cita_la_configuracion(reporte_v001):
    supuesto = next(s for s in reporte_v001["supuestos"] if s["tema"] == "Umbral de puntaje")

    assert "70" in supuesto["supuesto"]
    assert "config.yaml" in supuesto["fuente"]


def test_las_notas_avisan_de_datos_no_confirmados(reporte_v001):
    notas = " ".join(reporte_v001["observaciones"])

    assert "reclutador" in notas
    assert "no" in notas.lower()


def test_las_notas_avisan_de_la_fecha_relajada(reporte_v001):
    notas = " ".join(reporte_v001["observaciones"])

    assert "2026-11-08" in notas


# --- vacante incompleta ---

def test_una_vacante_incompleta_explica_el_bloqueo(reporte_v003):
    resultado = reporte_v003["resultado"]

    assert resultado["exito"] is False
    assert resultado["puestos_libres"] == 3
    assert resultado["requisito_bloqueante"] == "skills_obligatorios"
    assert resultado["motivo_incompleta"]
    assert resultado["bloqueantes"]


def test_una_vacante_incompleta_no_tiene_shortlist(reporte_v003, resultado_v003):
    assert reporte_v003["shortlist"] == []
    assert resultado_v003["requiere_revision_humana"] is True


# --- archivos generados ---

def test_se_generan_markdown_json_y_csv(tmp_path, resultado_v001, config):
    generado = generar_reporte(resultado_v001, config, directorio=tmp_path)
    rutas = generado["rutas"]

    assert rutas["markdown"].exists()
    assert rutas["json"].exists()
    assert rutas["csv"].exists()
    assert rutas["markdown"].name == "reporte_V001.md"
    assert rutas["json"].name == "reporte_V001.json"
    assert rutas["csv"].name == "puntajes_V001.csv"


def test_el_markdown_tiene_las_secciones_pedidas(reporte_v001):
    texto = renderizar_markdown(reporte_v001)

    assert "# Reporte de la vacante V001" in texto
    assert "## Shortlist" in texto
    assert "## Puntaje desglosado de todos los candidatos" in texto
    assert "## Criterios relajados (RF-06)" in texto
    assert "## Supuestos" in texto
    assert "C001" in texto


def test_el_json_es_legible_y_completo(tmp_path, resultado_v001, config):
    generado = generar_reporte(resultado_v001, config, directorio=tmp_path)
    datos = json.loads(generado["rutas"]["json"].read_text(encoding="utf-8"))

    assert datos["vacante"]["id"] == "V001"
    assert datos["shortlist"]
    assert datos["candidatos"]
    assert datos["supuestos"]
    assert datos["criterios_relajados"]


def test_el_csv_del_desglose_tiene_una_columna_por_componente(tmp_path, resultado_v001, config):
    generado = generar_reporte(resultado_v001, config, directorio=tmp_path)

    with generado["rutas"]["csv"].open("r", encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo))

    assert filas
    for clave, _ in COMPONENTES:
        assert clave in filas[0]
    assert all(fila["puntaje"] for fila in filas)


def test_el_reporte_es_reproducible(resultado_v001, config, tmp_path):
    uno = construir_reporte(resultado_v001, config)
    otro = construir_reporte(resultado_v001, config)

    assert uno == otro
    assert Path(tmp_path).exists()
