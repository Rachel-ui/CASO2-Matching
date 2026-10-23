"""Pruebas de la conversión correo -> vacante y del guardado del catálogo."""

import json

import pytest

from src.agentmail_cliente import Adjunto, Correo
from src.procesar_correo import guardar_vacante
from src.solicitud_vacante import ErrorVacante, extraer_vacante, validar_vacante


VACANTE = {
    "id": "V900",
    "titulo": "Desarrollador React",
    "descripcion": "Se busca experto en React.",
    "skills_obligatorios": ["React", "JavaScript"],
    "skills_deseables": ["TypeScript"],
    "experience_required": 2,
    "english_required": "B1",
    "availability_required": "2026-11-01",
    "modality": "remoto",
}


def correo(cuerpo="", adjuntos=None):
    return Correo(
        message_id="m1",
        thread_id="t1",
        remitente="RRHH <rrhh@example.com>",
        destinatarios=["bandeja@agentmail.to"],
        asunto="Solicitud de vacante",
        fecha="2026-10-20T10:00:00Z",
        cuerpo=cuerpo,
        adjuntos=adjuntos or [],
    )


def test_extrae_json_del_cuerpo_con_texto_alrededor():
    cuerpo = f"Hola, necesito cubrir este puesto:\n\n{json.dumps(VACANTE)}\n\nGracias."

    solicitud = extraer_vacante(correo(cuerpo))

    assert solicitud.vacante["id"] == "V900"
    assert solicitud.origen == "cuerpo del correo"


def test_extrae_desde_adjunto_json_si_el_cuerpo_no_trae_json():
    adjunto = Adjunto("att1", "vacante.json", "application/json")
    descargado = []

    def descargar(message_id, attachment_id):
        descargado.append((message_id, attachment_id))
        return json.dumps(VACANTE).encode()

    solicitud = extraer_vacante(correo("Adjunto la vacante.", [adjunto]), descargar)

    assert solicitud.vacante["id"] == "V900"
    assert solicitud.origen == "adjunto vacante.json"
    assert descargado == [("m1", "att1")]


def test_extrae_desde_adjunto_csv():
    csv_texto = (
        "id,titulo,skills_obligatorios,skills_deseables,experience_required,"
        "english_required,availability_required,modality\n"
        "V901,Backend Python,Python;SQL,Docker,3,B2,2026-11-15,hibrido\n"
    )

    solicitud = extraer_vacante(
        correo("Vacante adjunta", [Adjunto("att1", "vacante.csv", "text/csv")]),
        lambda _m, _a: csv_texto.encode(),
    )

    assert solicitud.vacante["skills_obligatorios"] == ["Python", "SQL"]
    assert solicitud.vacante["experience_required"] == 3
    assert solicitud.vacante["modality"] == "hibrido"


def test_acepta_contenedor_vacantes():
    datos = {"vacantes": [VACANTE]}

    solicitud = extraer_vacante(correo(json.dumps(datos)))

    assert solicitud.vacante["id"] == "V900"


def test_correo_sin_vacante_falla_con_motivo():
    with pytest.raises(ErrorVacante, match="No se pudo extraer la vacante"):
        extraer_vacante(correo("¿Me pasas las vacantes?"))


def test_vacante_incompleta_falla():
    incompleta = {k: v for k, v in VACANTE.items() if k != "modality"}

    with pytest.raises(ErrorVacante, match="modality"):
        extraer_vacante(correo(json.dumps(incompleta)))


def test_validar_vacante_detecta_campos_malos():
    mala = {**VACANTE, "english_required": "Z9", "availability_required": "31/12/2026"}

    problemas = validar_vacante(mala)

    assert any("inglés" in problema for problema in problemas)
    assert any("fecha" in problema for problema in problemas)


def test_guardar_vacante_agrega_sin_duplicar(tmp_path, monkeypatch):
    catalogo = tmp_path / "vacantes.json"
    catalogo.write_text(
        json.dumps({"vacantes": [{"id": "V001", "titulo": "Existente"}]}), encoding="utf-8"
    )
    monkeypatch.setattr("src.procesar_correo.ARCHIVO_VACANTES", catalogo)

    guardar_vacante(VACANTE, correo("x"), "cuerpo del correo")
    guardar_vacante({**VACANTE, "titulo": "Renombrada"}, correo("x"), "cuerpo del correo")

    vacantes = json.loads(catalogo.read_text(encoding="utf-8"))["vacantes"]

    assert [v["id"] for v in vacantes] == ["V001", "V900"]
    assert vacantes[1]["titulo"] == "Renombrada"
    # Un solo catálogo: no se crea un archivo por vacante.
    assert sorted(ruta.name for ruta in tmp_path.iterdir()) == ["vacantes.json"]
