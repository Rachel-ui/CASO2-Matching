"""Pruebas de la clasificación por contexto y del registro CSV.

Los textos de ejemplo son genéricos y no salen de ningún correo real: solo
sirven para comprobar que la estructura del mensaje se interpreta bien.
Las pruebas no escriben en data/: usan un directorio temporal.
"""

from datetime import date

import pytest

from src.agentmail_cliente import Correo
from src.grafo_correo import interpretar_y_guardar
from src.interpretar_texto import (
    TIPO_CANDIDATO,
    TIPO_DESCONOCIDO,
    TIPO_VACANTE,
    interpretar,
)
from src.registro_correos import CAMPOS, registrar_correo


HOY = date(2026, 10, 20)

# Perfil: primera persona, datos propios, antigüedad declarada.
TEXTO_PERFIL = (
    "Hola, me llamo Ana Pérez. Tengo 28 años y estoy formada como desarrolladora. "
    "Utilizo Python y SQL; tengo 4 años de experiencia. Mi nivel de inglés es B2."
)

# Necesidad: la empresa busca cubrir un cargo que aún no está ocupado.
TEXTO_PUESTO = (
    "Se busca analista con Python y SQL, 3 años de experiencia, inglés B2, "
    "modalidad híbrida, disponible desde el 1 de noviembre."
)

# Gestión: habla de temas del proyecto, sin describir un cargo ni un perfil.
TEXTO_GESTION = (
    "Hola, buenas tardes. Te comparto el avance de la semana y te consulto "
    "cuándo me puedes enviar la actualización del proyecto."
)


@pytest.fixture(autouse=True)
def sin_archivos_reales(tmp_path, monkeypatch):
    (tmp_path / "vacantes.json").write_text('{"vacantes": []}', encoding="utf-8")
    monkeypatch.setattr("src.candidatos.ARCHIVO_CANDIDATOS", tmp_path / "candidatos.csv")
    monkeypatch.setattr("src.registro_correos.ARCHIVO_CORREOS", tmp_path / "registro.csv")
    monkeypatch.setattr("src.procesar_correo.ARCHIVO_VACANTES", tmp_path / "vacantes.json")
    return tmp_path


def test_reconoce_perfil_por_primera_persona():
    resultado = interpretar(TEXTO_PERFIL, HOY)

    assert resultado.tipo == TIPO_CANDIDATO
    assert resultado.datos["nombre"] == "Ana Pérez"
    assert resultado.datos["experience_years"] == 4  # no la edad (28)
    assert resultado.datos["english_level"] == "B2"
    assert resultado.evidencia["perfil"]


def test_reconoce_puesto_por_necesidad_de_contratacion():
    resultado = interpretar(TEXTO_PUESTO, HOY)

    assert resultado.tipo == TIPO_VACANTE
    assert resultado.datos["skills_obligatorios"] == ["Python", "SQL"]
    assert resultado.datos["experience_required"] == 3
    assert resultado.datos["english_required"] == "B2"
    assert resultado.datos["modality"] == "hibrido"
    assert resultado.datos["availability_required"] == "2026-11-01"


def test_mencionar_el_tema_no_alcanza_para_ser_vacante():
    """Un correo de gestión que nombra vacantes o requisitos no es una oferta."""

    texto = (
        "Buenos días. Te escribo para coordinar la reunión del lunes y revisar "
        "los requisitos y las vacantes que quedaron pendientes. Quedo atenta."
    )

    assert interpretar(texto, HOY).tipo == TIPO_DESCONOCIDO


def test_correo_de_gestion_se_descarta():
    assert interpretar(TEXTO_GESTION, HOY).tipo == TIPO_DESCONOCIDO


def test_texto_vacio_o_cordial_es_desconocido():
    assert interpretar("hola, buenas tardes", HOY).tipo == TIPO_DESCONOCIDO


def test_documentacion_tecnica_no_es_un_perfil():
    """Un texto con palabras técnicas pero sin describir a nadie no es candidato."""

    texto = (
        "Bienvenido. Este mensaje explica cómo usar la API REST del servicio y "
        "dónde encontrar la documentación de cada endpoint."
    )

    assert interpretar(texto, HOY).tipo == TIPO_DESCONOCIDO


def test_perfil_sin_datos_estructurados_igual_se_guarda():
    """Aunque no traiga el esquema completo, un perfil se registra como candidato."""

    texto = "Hola, soy Juan Soto y tengo experiencia con React y JavaScript."
    resultado = interpretar(texto, HOY)

    assert resultado.tipo == TIPO_CANDIDATO
    assert resultado.datos["skills"] == "React;JavaScript"
    assert resultado.datos["experience_years"] is None


def test_detecta_fecha_relativa():
    resultado = interpretar("Se busca QA con experiencia, disponible en 2 semanas", HOY)

    assert resultado.tipo == TIPO_VACANTE
    assert resultado.datos["availability_required"] == "2026-11-03"


def test_marca_los_datos_que_faltan():
    resultado = interpretar("Se busca desarrollador con Python", HOY)

    assert resultado.tipo == TIPO_VACANTE
    faltantes = " ".join(resultado.advertencias)
    assert "inglés" in faltantes
    assert "modalidad" in faltantes


def _correo(texto, message_id="m1"):
    return Correo(
        message_id=message_id,
        thread_id="t1",
        remitente="remitente@example.com",
        destinatarios=["bandeja@agentmail.to"],
        asunto="Correo",
        fecha="2026-10-20T10:00:00Z",
        cuerpo=texto,
    )


def test_grafo_no_crea_un_json_por_correo(sin_archivos_reales):
    """Todo se guarda en CSV/catálogo: ningún archivo extra por correo."""

    for indice, texto in enumerate((TEXTO_PERFIL, TEXTO_PUESTO)):
        interpretar_y_guardar(texto, _correo(texto, f"m{indice}"))

    archivos = sorted(ruta.name for ruta in sin_archivos_reales.iterdir())

    assert archivos == ["candidatos.csv", "registro.csv", "vacantes.json"]
    assert not any(ruta.is_dir() for ruta in sin_archivos_reales.iterdir())


def test_grafo_guarda_perfil_en_csv(sin_archivos_reales):
    estado = interpretar_y_guardar(TEXTO_PERFIL, _correo(TEXTO_PERFIL))

    assert estado["accion"] == "candidato_guardado"

    import csv

    with (sin_archivos_reales / "candidatos.csv").open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo))

    assert filas[-1]["nombre"] == "Ana Pérez"
    assert filas[-1]["experience_years"] == "4"


def test_grafo_registra_todos_los_correos_con_su_texto(sin_archivos_reales):
    """La verificación queda en el CSV: texto original, tipo y acción."""

    import csv

    for indice, texto in enumerate((TEXTO_PERFIL, TEXTO_PUESTO, TEXTO_GESTION)):
        interpretar_y_guardar(texto, _correo(texto, f"m{indice}"))

    with (sin_archivos_reales / "registro.csv").open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo))

    assert list(filas[0]) == list(CAMPOS)
    assert [fila["tipo_detectado"] for fila in filas] == [
        TIPO_CANDIDATO,
        TIPO_VACANTE,
        TIPO_DESCONOCIDO,
    ]
    assert [fila["accion"] for fila in filas] == [
        "candidato_guardado",
        "vacante_guardada",
        "descartado",
    ]
    assert filas[0]["texto"].startswith("Hola, me llamo Ana Pérez")
    assert filas[1]["senales_detectadas"]


def test_registro_permite_verificar_y_actualiza_la_misma_fila(tmp_path, monkeypatch):
    monkeypatch.setattr("src.registro_correos.ARCHIVO_CORREOS", tmp_path / "registro.csv")

    correo = _correo(TEXTO_PERFIL)
    interpretado = interpretar(TEXTO_PERFIL, HOY)

    registrar_correo(correo, interpretado, accion="candidato_guardado", identificador="C001")
    registrar_correo(correo, interpretado, tipo_verificado=TIPO_VACANTE)

    import csv

    with (tmp_path / "registro.csv").open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo))

    assert len(filas) == 1
    assert filas[0]["tipo_verificado"] == TIPO_VACANTE
    assert filas[0]["coincide"] == "no"
    assert filas[0]["accion"] == "candidato_guardado"

