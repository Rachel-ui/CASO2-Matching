"""Pruebas de RF-16: clasificación de correos y cola de vacantes.

Fase 1 por reglas (sin red) y fase 2 con un LLM doble. Lo que se verifica:

- Cada correo termina en una sola clase: vacante nueva, duplicado o no
  relacionado.
- Solo la vacante nueva entra a la cola y dispara el matching.
- Un reenvío o la misma vacante con otro ID/mensaje es duplicado.
- Un correo sin rol o sin skills obligatorios va a revisión humana; no se
  inventan criterios.
- Lo que no describe un puesto (gestión, candidato, boletín) es no
  relacionado.
- Con LLM, la validación y la cola siguen decidiéndose en código y, si el LLM
  falla, se usan las reglas.
"""

import json
from pathlib import Path

import pytest

from src.bandeja_simulada import cargar_bandeja
from src.clasificar_correos import (
    DUPLICADO,
    NO_RELACIONADO,
    REVISION_HUMANA,
    VACANTE_NUEVA,
    clasificar_con_llm,
    clasificar_correo,
    clasificar_por_reglas,
    encolar,
    estado_cola,
    guardar_cola,
    cargar_cola,
    huella_vacante,
    marcar_procesada,
    siguiente_de_cola,
    tiene_rol_y_skills,
    vacia_cola,
)
from src.configuracion import MODO_CON_LLM, MODO_SIN_LLM
from src.llm_cliente import ErrorLLM


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


def correo(bandeja, message_id):
    return next(c for c in bandeja["correos"] if c["message_id"] == message_id)


def correo_libre(message_id, asunto, cuerpo, timestamp="2026-10-20T09:00:00"):
    """Correo de texto libre, sin `vacante_estructurada` (bandeja real)."""

    return {
        "message_id": message_id,
        "timestamp": timestamp,
        "remitente": "rrhh@empresa.example",
        "asunto": asunto,
        "cuerpo": cuerpo,
    }


class LLM_Doble:
    """Sustituto del chat model: responde el JSON que se le indique."""

    def __init__(self, texto="", error=None):
        self.texto = texto
        self.error = error
        self.mensajes = []

    def invoke(self, mensajes):
        self.mensajes.append(mensajes)
        if self.error:
            raise self.error

        class Respuesta:
            content = self.texto

        return Respuesta()


# --- fase 1: cada correo cae en una sola clase ---

def test_la_bandeja_se_clasifica_en_las_tres_clases():
    clases = {
        c["message_id"]: clasificar_por_reglas(c)["clase"]
        for c in cargar_bandeja()["correos"]
    }

    # b4 es un reenvío de b1: por sí solo parece vacante, pero al encolarse
    # se detecta como duplicado (se prueba más abajo).
    assert clases["b1"] == VACANTE_NUEVA
    assert clases["b2"] == VACANTE_NUEVA
    assert clases["b3"] == VACANTE_NUEVA
    assert clases["b5"] == REVISION_HUMANA
    assert clases["b6"] == NO_RELACIONADO
    assert clases["b7"] == NO_RELACIONADO
    assert clases["b10"] == NO_RELACIONADO


def test_una_vacante_sin_skills_va_a_revision_humana():
    clasificado = clasificar_por_reglas(correo(cargar_bandeja(), "b5"))

    assert clasificado["clase"] == REVISION_HUMANA
    assert "skills obligatorios" in clasificado["motivo"]


def test_el_correo_de_gestion_no_es_vacante():
    clasificado = clasificar_por_reglas(correo(cargar_bandeja(), "b0"))

    assert clasificado["clase"] != VACANTE_NUEVA


def test_el_boletin_y_la_factura_no_se_relacionan():
    bandeja = cargar_bandeja()

    for message_id in ("b7", "b8", "b9"):
        assert clasificar_por_reglas(correo(bandeja, message_id))["clase"] == NO_RELACIONADO


def test_un_candidato_no_se_relaciona():
    clasificado = clasificar_por_reglas(correo(cargar_bandeja(), "b6"))

    assert clasificado["clase"] == NO_RELACIONADO
    assert clasificado["tipo_texto"] == "candidato"


def test_una_vacante_de_texto_libre_entra_si_tiene_rol_y_skills():
    nuevo = correo_libre(
        "x1",
        "Vacante: Desarrollador Python",
        "Hola, buscamos un Desarrollador Python con Python, SQL y Git para el "
        "equipo de datos. Remoto, inglés B1, 3 años de experiencia, disponible "
        "para el 2026-11-01.",
    )

    clasificado = clasificar_por_reglas(nuevo)

    assert clasificado["clase"] == VACANTE_NUEVA
    assert tiene_rol_y_skills(clasificado["vacante"])
    assert "Python" in clasificado["vacante"]["skills_obligatorios"]


def test_una_vacante_de_texto_sin_skills_va_a_revision():
    nuevo = correo_libre(
        "x2",
        "Necesitamos cubrir un puesto",
        "Hola, necesitamos contratar a alguien para atención al cliente. "
        "No tenemos el perfil definido todavía.",
    )

    clasificado = clasificar_por_reglas(nuevo)

    assert clasificado["clase"] == REVISION_HUMANA
    assert clasificado["vacante"] is None
    assert clasificado["problemas"]


def test_no_se_inventan_criterios_que_el_correo_no_trae():
    nuevo = correo_libre(
        "x3",
        "Vacante: Backend",
        "Hola, necesitamos contratar un Backend con Python y SQL.",
    )

    datos = clasificar_por_reglas(nuevo)["vacante"]

    assert datos["experience_required"] is None
    assert datos["english_required"] is None
    assert datos["availability_required"] is None


def test_la_estructura_que_no_coincide_con_el_texto_va_a_revision():
    inconsistente = dict(correo(cargar_bandeja(), "b1"))
    inconsistente["cuerpo"] = "Hola, buscamos un backend con Java y 10 años de experiencia."

    clasificado = clasificar_por_reglas(inconsistente)

    assert clasificado["clase"] == REVISION_HUMANA


# --- la cola: solo la vacante nueva entra ---

def test_una_vacante_nueva_entra_a_la_cola():
    cola = vacia_cola()
    decision = encolar(correo(cargar_bandeja(), "b1"), cola)

    assert decision["clase"] == VACANTE_NUEVA
    assert decision["disparo_matching"] is True
    assert decision["en_cola"] is True
    assert estado_cola(cola)["vacantes"] == 1
    assert siguiente_de_cola(cola)["vacante"]["id"] == "B001"


def test_un_reenvio_es_duplicado_y_no_entra_a_la_cola():
    bandeja = cargar_bandeja()
    cola = vacia_cola()

    encolar(correo(bandeja, "b1"), cola)
    decision = encolar(correo(bandeja, "b4"), cola)

    assert decision["clase"] == DUPLICADO
    assert decision["disparo_matching"] is False
    assert decision["en_cola"] is False
    assert decision["duplicado_de"] == "b1"
    assert estado_cola(cola)["vacantes"] == 1
    assert estado_cola(cola)["duplicados"] == 1


def test_la_misma_vacante_con_otro_id_y_mensaje_es_duplicado():
    bandeja = cargar_bandeja()
    cola = vacia_cola()
    encolar(correo(bandeja, "b1"), cola)

    copia = dict(correo(bandeja, "b1"))
    copia["message_id"] = "b1-copia"
    copia["asunto"] = "Otra vez la vacante"
    copia["vacante_estructurada"] = {**copia["vacante_estructurada"], "id": "B001-BIS"}

    decision = encolar(copia, cola)

    assert decision["clase"] == DUPLICADO
    # Apunta a la vacante original, no a la copia con ID nuevo.
    assert decision["vacante_id"] == "B001"


def test_la_huella_cambia_si_cambian_los_criterios():
    bandeja = cargar_bandeja()
    vacante = correo(bandeja, "b1")["vacante_estructurada"]
    otra = {**vacante, "experience_required": 5}

    assert huella_vacante(vacante) == huella_vacante(dict(vacante))
    assert huella_vacante(vacante) != huella_vacante(otra)


def test_una_revision_humana_queda_registrada_y_no_dispara():
    cola = vacia_cola()
    decision = encolar(correo(cargar_bandeja(), "b5"), cola)

    assert decision["clase"] == REVISION_HUMANA
    assert decision["disparo_matching"] is False
    assert estado_cola(cola)["revision_humana"] == 1
    assert estado_cola(cola)["vacantes"] == 0


def test_un_correo_no_relacionado_no_toca_la_cola():
    cola = vacia_cola()
    decision = encolar(correo(cargar_bandeja(), "b6"), cola)

    assert decision["clase"] == NO_RELACIONADO
    assert decision["en_cola"] is False
    assert estado_cola(cola) == {
        "vacantes": 0,
        "pendientes": 0,
        "duplicados": 0,
        "revision_humana": 0,
    }


def test_la_vacante_sale_de_la_cola_al_procesarla():
    cola = vacia_cola()
    encolar(correo(cargar_bandeja(), "b1"), cola)

    assert siguiente_de_cola(cola) is not None
    marcar_procesada(cola, "B001")

    assert siguiente_de_cola(cola) is None
    assert estado_cola(cola)["pendientes"] == 0


def test_la_cola_se_guarda_y_se_recupera(tmp_path):
    ruta = tmp_path / "cola_vacantes.json"
    cola = vacia_cola()
    encolar(correo(cargar_bandeja(), "b1"), cola)
    guardar_cola(cola, ruta)

    recuperada = cargar_cola(ruta)

    assert recuperada == cola
    assert json.loads(ruta.read_text(encoding="utf-8"))["vacantes"][0]["vacante"]["id"] == "B001"


def test_la_cola_inexistente_se_lee_vacia(tmp_path):
    assert cargar_cola(tmp_path / "no_existe.json") == vacia_cola()


# --- la cola sigue el orden de llegada ---

def test_la_cola_respeta_el_orden_de_llegada():
    bandeja = cargar_bandeja()
    cola = vacia_cola()
    for message_id in ("b1", "b2", "b3"):
        encolar(correo(bandeja, message_id), cola)

    ids = [r["vacante"]["id"] for r in cola["vacantes"]]

    assert ids == ["B001", "B002", "B003"]


# --- fase 2: LLM ---

def test_con_llm_se_usa_el_modo_configurado(monkeypatch):
    monkeypatch.setenv("AGENTE_MODO", MODO_CON_LLM)
    llm = LLM_Doble(
        texto=json.dumps(
            {
                "clase": "vacante_nueva",
                "motivo": "El correo pide un backend.",
                "vacante": {
                    "titulo": "Backend",
                    "skills_obligatorios": ["Python", "SQL"],
                    "experience_required": 3,
                    "english_required": "B1",
                    "availability_required": "2026-11-01",
                    "modality": "remoto",
                },
            }
        )
    )

    clasificado = clasificar_correo(correo_libre("y1", "Vacante", "Texto"), llm=llm)

    assert clasificado["clase"] == VACANTE_NUEVA
    assert clasificado["fuente"] == "llm"
    assert clasificado["vacante"]["skills_obligatorios"] == ["Python", "SQL"]


def test_el_llm_no_puede_colar_una_vacante_sin_rol_ni_skills():
    llm = LLM_Doble(
        texto=json.dumps(
            {
                "clase": "vacante_nueva",
                "motivo": "Parece vacante.",
                "vacante": {"titulo": "", "skills_obligatorios": []},
            }
        )
    )

    clasificado = clasificar_con_llm(correo_libre("y2", "Hola", "Texto"), llm)

    assert clasificado["clase"] == REVISION_HUMANA


def test_el_llm_no_decide_que_entra_a_la_cola():
    """Aunque el LLM diga 'duplicado', la cola se decide en código."""

    bandeja = cargar_bandeja()
    cola = vacia_cola()
    encolar(correo(bandeja, "b1"), cola, modo=MODO_SIN_LLM)

    llm = LLM_Doble(
        texto=json.dumps(
            {
                "clase": "duplicado",
                "motivo": "Yo creo que ya llegó.",
                "vacante": {
                    "titulo": "Desarrollador Go",
                    "skills_obligatorios": ["Go"],
                    "modality": "remoto",
                },
            }
        )
    )
    decision = encolar(correo_libre("y3", "Vacante Go", "Buscamos Go."), cola, modo=MODO_CON_LLM, llm=llm)

    # Es una vacante distinta: entra a la cola pese a lo que diga el LLM.
    assert decision["clase"] == VACANTE_NUEVA
    assert decision["en_cola"] is True
    assert estado_cola(cola)["vacantes"] == 2


def test_un_duplicado_se_detecta_aunque_lo_clasifique_el_llm():
    bandeja = cargar_bandeja()
    cola = vacia_cola()
    encolar(correo(bandeja, "b1"), cola)

    vacante = dict(correo(bandeja, "b1")["vacante_estructurada"])
    llm = LLM_Doble(
        texto=json.dumps({"clase": "vacante_nueva", "motivo": "Viene de nuevo.", "vacante": vacante})
    )
    decision = encolar(
        correo_libre("y4", "Solicitud", "Solicitud de vacante otra vez."),
        cola,
        modo=MODO_CON_LLM,
        llm=llm,
    )

    assert decision["clase"] == DUPLICADO
    assert decision["disparo_matching"] is False


def test_si_el_llm_falla_se_usan_las_reglas(monkeypatch):
    monkeypatch.setenv("AGENTE_MODO", MODO_CON_LLM)
    llm = LLM_Doble(error=ErrorLLM("sin clave"))

    clasificado = clasificar_correo(correo(cargar_bandeja(), "b1"), llm=llm)

    assert clasificado["clase"] == VACANTE_NUEVA
    assert clasificado["fuente"] == "reglas"
    assert any("reglas" in advertencia for advertencia in clasificado["advertencias"])


def test_si_el_llm_responde_algo_que_no_es_json_se_usan_las_reglas(monkeypatch):
    monkeypatch.setenv("AGENTE_MODO", MODO_CON_LLM)
    llm = LLM_Doble(texto="No sé qué es esto.")

    clasificado = clasificar_correo(correo(cargar_bandeja(), "b6"), llm=llm)

    assert clasificado["clase"] == NO_RELACIONADO
    assert clasificado["fuente"] == "reglas"
