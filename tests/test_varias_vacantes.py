"""Pruebas de RF-13: varias vacantes en una corrida, una por una desde la cola.

La bandeja trae más de una vacante. El agente no procesa todas de golpe: las
va encolando y, al cerrar cada ciclo, corre el matching de cada una, en el
orden en que llegaron. Cada vacante deja su propio reporte.

Se verifica:

- que las cuatro vacantes de la bandeja se procesen en la misma corrida;
- que el orden sea el de llegada y no el del ID;
- que entre en la cola solo lo que entra como vacante nueva;
- que cada vacante tenga su reporte y que el índice apunte a todos;
- que una vacante con error no frene a las demás.
"""

from pathlib import Path

import pytest

from src.bandeja_simulada import ejecutar_bandeja
from src.clasificar_correos import vacia_cola
from src.configuracion import cargar_configuracion
from src.interpretar_correo_bandeja import procesar_cola
from src.reporte_vacante import generar_reportes_bandeja


@pytest.fixture(scope="module")
def corrida(tmp_path_factory):
    """Una corrida completa de la bandeja, sin tocar el registro real."""

    directorio = tmp_path_factory.mktemp("bandeja")
    return ejecutar_bandeja(
        ruta_procesados=directorio / "procesados.json",
        reiniciar=True,
        en_silencio=True,
    )


# --- varias vacantes en una sola corrida ---

def test_la_corrida_procesa_todas_las_vacantes_de_la_bandeja(corrida):
    assert corrida["orden_procesamiento"] == ["V001", "V002", "V004", "V003"]
    assert corrida["matching_disparado"] == corrida["orden_procesamiento"]


def test_cada_vacante_tiene_su_resultado(corrida):
    assert set(corrida["resultados"]) == {"V001", "V002", "V004", "V003"}
    for estado in corrida["resultados"].values():
        assert estado["vacante_actual"]["id"]


def test_una_sola_corrida_basta_para_todas_las_vacantes(corrida):
    """No hace falta volver a correr la bandeja para la segunda vacante."""

    assert corrida["ciclos_ejecutados"] == 8
    assert len(corrida["resultados"]) == 4


# --- el orden es el de llegada ---

def test_el_orden_es_el_de_llegada_y_no_el_del_id(corrida):
    orden = corrida["orden_procesamiento"]

    assert orden != sorted(orden)
    assert orden.index("V004") < orden.index("V003")


def test_las_vacantes_de_un_mismo_ciclo_salen_en_orden(corrida):
    ciclo_v004 = next(c for c in corrida["ciclos"] if "V004" in c["matching_disparado"])

    assert ciclo_v004["vacantes_en_cola"] == ["V004"]


def test_la_cola_queda_vacia_al_terminar(corrida):
    assert corrida["vacantes_pendientes"] == []


# --- qué entra y qué no a la cola ---

def test_el_duplicado_y_la_revision_no_se_procesan(corrida):
    assert "b4" not in corrida["orden_procesamiento"]
    assert len(corrida["clasificacion"]["duplicados"]) == 1
    assert len(corrida["clasificacion"]["revision_humana"]) == 1


def test_no_hay_errores_de_matching(corrida):
    assert corrida["errores_matching"] == []


# --- una vacante rota no frena a las demás ---

def test_una_vacante_con_error_no_frena_la_cola(monkeypatch):
    llamadas = []

    # `procesar_cola` importa la función dentro de la llamada, así que se
    # reemplaza en su módulo de origen.
    from src import ejecutar_matching

    original = ejecutar_matching.invocar_con_limite

    def falla_para_v002(estado_inicial, config):
        vacante_id = estado_inicial["vacante_actual"]["id"]
        llamadas.append(vacante_id)
        if vacante_id == "V002":
            raise RecursionError("se alcanzó el recursion_limit")
        return original(estado_inicial, config)

    monkeypatch.setattr(ejecutar_matching, "invocar_con_limite", falla_para_v002)

    cola = vacia_cola()
    cola["vacantes"] = [
        {"vacante": {"id": "V001", "titulo": "A", "skills_obligatorios": ["Python"]}},
        {"vacante": {"id": "V002", "titulo": "B", "skills_obligatorios": ["Python"]}},
        {"vacante": {"id": "V003", "titulo": "C", "skills_obligatorios": ["Python"]}},
    ]
    for registro in cola["vacantes"]:
        registro["vacante"].update(
            {
                "skills_deseables": [],
                "experience_required": 0,
                "english_required": "A1",
                "availability_required": "2026-12-31",
                "modality": "remoto",
            }
        )
    vacantes, estado = [], {}

    procesadas = procesar_cola(cola, vacantes, estado)

    assert llamadas == ["V001", "V002", "V003"]
    assert [p["vacante_id"] for p in procesadas] == ["V001", "V002", "V003"]
    error = next(p for p in procesadas if p["vacante_id"] == "V002")
    assert error["estado"] == "error"
    assert error["errores"]
    # Las otras dos sí se procesaron y la cola quedó drenada.
    assert {p["vacante_id"] for p in procesadas if p["estado"] != "error"} == {"V001", "V003"}
    assert all(registro.get("procesada") for registro in cola["vacantes"])


# --- un reporte por vacante ---

def test_se_genera_un_reporte_por_vacante(corrida, tmp_path):
    config = cargar_configuracion()

    generados = generar_reportes_bandeja(corrida, config, directorio=tmp_path)

    assert [g["vacante_id"] for g in generados] == ["V001", "V002", "V004", "V003"]
    for generado in generados:
        assert generado["rutas"]["markdown"].exists()
        assert generado["rutas"]["json"].exists()
        assert generado["rutas"]["csv"].exists()


def test_los_reportes_respetan_el_orden_de_la_cola(corrida, tmp_path):
    generados = generar_reportes_bandeja(corrida, cargar_configuracion(), directorio=tmp_path)

    ids = [g["reporte"]["vacante"]["id"] for g in generados]

    assert ids == corrida["orden_procesamiento"]


def test_el_indice_apunta_a_todos_los_reportes(corrida, tmp_path):
    generados = generar_reportes_bandeja(corrida, cargar_configuracion(), directorio=tmp_path)

    indice = tmp_path / "reportes_bandeja.md"
    texto = indice.read_text(encoding="utf-8")

    assert indice.exists()
    for generado in generados:
        vacante_id = generado["vacante_id"]
        assert f"reporte_{vacante_id}.md" in texto
        assert vacante_id in texto
    assert "una por una" in texto


def test_cada_reporte_dice_su_vacante(corrida, tmp_path):
    generados = generar_reportes_bandeja(corrida, cargar_configuracion(), directorio=tmp_path)

    for generado in generados:
        texto = generado["rutas"]["markdown"].read_text(encoding="utf-8")
        assert f"# Reporte de la vacante {generado['vacante_id']}" in texto


def test_los_reportes_no_se_pisan_entre_vacantes(corrida, tmp_path):
    generar_reportes_bandeja(corrida, cargar_configuracion(), directorio=tmp_path)

    archivos = sorted(p.name for p in Path(tmp_path).glob("reporte_*.md"))

    assert archivos == sorted(
        f"reporte_{vacante_id}.md" for vacante_id in corrida["orden_procesamiento"]
    )
