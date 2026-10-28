
"""Pruebas de RF-15: ciclos de 1 hora sobre la bandeja simulada.

Un ciclo = 1 hora simulada. En cada ciclo se leen los correos que llegaron
hasta esa hora, se guardan sus ids para no procesarlos dos veces y el
matching solo arranca cuando llega un correo de vacante. La corrida termina
al llegar a la hora máxima sin vacantes en cola.
"""

import json
from pathlib import Path

import pytest

from src.bandeja_simulada import (
    HORAS_POR_CICLO,
    MAX_HORAS_SIMULADAS,
    cargar_bandeja,
    cargar_procesados,
    correos_hasta_hora,
    ejecutar_bandeja,
    es_vacante,
    guardar_procesados,
)
from src.interpretar_correo_bandeja import clasificar_correo
from src.leer_correos import HORAS_SIMULADAS_POR_CORRIDA, ventana_simulada
from src.configuracion import cargar_configuracion


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


@pytest.fixture
def bandeja_temporal(tmp_path):
    """Copia de la bandeja con su registro de procesados aparte."""

    origen = DATA / "bandeja.json"
    destino = tmp_path / "bandeja.json"
    destino.write_text(origen.read_text(encoding="utf-8-sig"), encoding="utf-8")
    return destino, tmp_path / "bandeja_procesados.json"


def correo(bandeja, message_id):
    return next(c for c in bandeja["correos"] if c["message_id"] == message_id)


# --- ciclos de 1 hora simulada ---

def test_un_ciclo_es_una_hora_simulada():
    assert HORAS_POR_CICLO == 1


def test_en_cada_ciclo_solo_llegan_los_correos_hasta_esa_hora():
    from datetime import datetime

    bandeja = cargar_bandeja()
    inicio = datetime.fromisoformat(bandeja["inicio"])

    primera = correos_hasta_hora(bandeja["correos"], inicio, 1)
    tercera = correos_hasta_hora(bandeja["correos"], inicio, 3)

    # Inicio 06:00: b0 (06:30) entra en la hora 1 y b1 (08:10) en la hora 3.
    assert [c["message_id"] for c in primera] == ["b0"]
    assert [c["message_id"] for c in tercera] == ["b0", "b1"]


def test_la_corrida_cubre_las_primeras_3_o_4_horas(bandeja_temporal):
    ruta_bandeja, ruta_procesados = bandeja_temporal

    resultado = ejecutar_bandeja(
        ruta_bandeja=ruta_bandeja,
        ruta_procesados=ruta_procesados,
        reiniciar=True,
    )

    # Como en el caso 1, la corrida cierra en cuanto llegó la última vacante
    # (b3 a las 7 h del inicio); las 24 h no se esperan completas.
    assert 3 <= resultado["ciclos_ejecutados"] <= 8
    assert resultado["motivo_fin"] == "bandeja_agotada"
    # Lo que quedaba en la bandeja no eran vacantes: se registran al final.
    assert set(resultado["correos_pendientes"]) <= {"b5", "b6", "b7", "b8", "b9"}


def test_nunca_pasa_de_la_hora_maxima(bandeja_temporal):
    ruta_bandeja, ruta_procesados = bandeja_temporal

    resultado = ejecutar_bandeja(
        hora_maxima=100,
        ruta_bandeja=ruta_bandeja,
        ruta_procesados=ruta_procesados,
        reiniciar=True,
    )

    assert resultado["hora_maxima"] == MAX_HORAS_SIMULADAS
    assert resultado["ciclos_ejecutados"] <= MAX_HORAS_SIMULADAS


def test_termina_con_la_cola_vacia(bandeja_temporal):
    ruta_bandeja, ruta_procesados = bandeja_temporal

    resultado = ejecutar_bandeja(
        ruta_bandeja=ruta_bandeja,
        ruta_procesados=ruta_procesados,
        reiniciar=True,
    )

    assert resultado["vacantes_en_cola"] == []
    # Ninguna vacante queda sin leer cuando la corrida cierra.
    assert set(resultado["matching_disparado"]) >= {"V001", "V002", "V003"}


# --- ids guardados: nada se procesa dos veces ---

def test_los_ids_quedan_guardados_sin_repetir(tmp_path):
    ruta = tmp_path / "procesados.json"

    guardar_procesados(["b1", "b2", "b1"], ruta)

    assert cargar_procesados(ruta) == ["b1", "b2"]


def test_una_segunda_corrida_no_reprocesa_nada(bandeja_temporal):
    ruta_bandeja, ruta_procesados = bandeja_temporal

    primera = ejecutar_bandeja(
        ruta_bandeja=ruta_bandeja, ruta_procesados=ruta_procesados, reiniciar=True
    )
    segunda = ejecutar_bandeja(
        ruta_bandeja=ruta_bandeja, ruta_procesados=ruta_procesados
    )

    assert segunda["correos_procesados"] == primera["correos_procesados"]
    assert segunda["matching_disparado"] == []
    assert all(ciclo["correos_nuevos"] == [] for ciclo in segunda["ciclos"])


def test_el_reenvio_no_vuelve_a_disparar_el_matching():
    resultado = ejecutar_bandeja(reiniciar=True)

    ciclos_b4 = [
        ciclo for ciclo in resultado["ciclos"] if "b4" in ciclo["correos_nuevos"]
    ]
    assert ciclos_b4
    acciones = {a["message_id"]: a["accion"] for a in ciclos_b4[0]["acciones"]}
    # RF-16: el reenvío se clasifica como duplicado de la vacante ya recibida.
    assert acciones["b4"] in {"ya_procesada", "reenvio", "duplicado"}
    assert resultado["matching_disparado"].count("V001") == 1


# --- el matching solo arranca con un correo de vacante ---

def test_solo_las_vacantes_disparan_el_matching():
    bandeja = cargar_bandeja()
    resultado = ejecutar_bandeja(reiniciar=True)

    disparadas = set(resultado["matching_disparado"])
    for correo_actual in bandeja["correos"]:
        if correo_actual["message_id"] == "b4":  # reenvío de V001
            continue
        if es_vacante(correo_actual):
            assert clasificar_correo(correo_actual)["vacante"]["id"] in disparadas
        else:
            assert clasificar_correo(correo_actual)["tipo"] != "vacante"


def test_un_correo_de_gestion_no_dispara_el_matching():
    bandeja = cargar_bandeja()
    gestion = correo(bandeja, "b0")

    clasificado = clasificar_correo(gestion)

    assert clasificado["tipo"] == "desconocido"
    assert es_vacante(gestion) is False


def test_un_candidato_no_dispara_el_matching():
    bandeja = cargar_bandeja()
    candidato = correo(bandeja, "b6")

    assert clasificar_correo(candidato)["tipo"] == "candidato"
    assert es_vacante(candidato) is False


def test_un_correo_de_vacante_dispara_el_matching():
    bandeja = cargar_bandeja()
    vacante = correo(bandeja, "b1")

    assert es_vacante(vacante) is True
    assert clasificar_correo(vacante)["vacante"]["id"] == "V001"


def test_el_ciclo_marca_cuando_dispara_el_matching(bandeja_temporal):
    ruta_bandeja, ruta_procesados = bandeja_temporal

    resultado = ejecutar_bandeja(
        ruta_bandeja=ruta_bandeja, ruta_procesados=ruta_procesados, reiniciar=True
    )

    ciclo_b1 = next(c for c in resultado["ciclos"] if "b1" in c["correos_nuevos"])
    assert ciclo_b1["matching_disparado"] == ["V001"]


# --- la simulación no toca el dataset real ---

def test_la_corrida_no_modifica_el_dataset():
    antes = {
        "vacantes": (DATA / "vacantes.json").read_text(encoding="utf-8-sig"),
        "candidatos": (DATA / "candidatos.csv").read_text(encoding="utf-8-sig"),
    }

    ejecutar_bandeja(reiniciar=True)

    assert (DATA / "vacantes.json").read_text(encoding="utf-8-sig") == antes["vacantes"]
    assert (DATA / "candidatos.csv").read_text(encoding="utf-8-sig") == antes["candidatos"]


def test_las_vacantes_procesadas_quedan_listadas():
    resultado = ejecutar_bandeja(reiniciar=True)

    assert resultado["vacantes"]
    assert set(resultado["vacantes"]) >= {"V001", "V002", "V003"}
    assert set(resultado["resultados"]) == set(resultado["vacantes"])


# --- coherencia con RNF-04 ---

def test_la_hora_maxima_no_pasa_la_ventana_simulada():
    config = cargar_configuracion()

    assert MAX_HORAS_SIMULADAS <= 24
    assert ventana_simulada(config) <= MAX_HORAS_SIMULADAS
    assert HORAS_SIMULADAS_POR_CORRIDA == 8


def test_la_vacante_del_correo_coincide_con_el_catalogo():
    """El correo no puede pedir otra cosa que la vacante ya publicada.

    Si divergen, el mismo puesto da una shortlist distinta según se procese
    desde la bandeja o desde el catálogo.
    """

    from src.bandeja_simulada import cargar_bandeja as leer_bandeja

    with (DATA / "vacantes.json").open("r", encoding="utf-8-sig") as archivo:
        catalogo = {v["id"]: v for v in json.load(archivo)["vacantes"]}

    criterios = (
        "skills_obligatorios",
        "skills_deseables",
        "experience_required",
        "english_required",
        "availability_required",
        "modality",
    )
    for correo_actual in leer_bandeja()["correos"]:
        vacante = correo_actual.get("vacante_estructurada")
        if not isinstance(vacante, dict) or vacante.get("id") not in catalogo:
            continue
        publicada = catalogo[vacante["id"]]
        for campo in criterios:
            assert vacante.get(campo) == publicada.get(campo), (
                f"{correo_actual['message_id']} ({vacante['id']}): '{campo}' "
                "no coincide con data/vacantes.json"
            )
