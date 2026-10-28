
import csv
import json
from pathlib import Path

from src.configuracion import cargar_configuracion
from src.duplicados import depurar_duplicados
from src.estado_agente import crear_estado_inicial
from src.ejecutar_matching import invocar_con_limite
from src.grafo_matching import app_matching


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


def cargar_candidatos():
    with (DATA / "candidatos.csv").open("r", encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def cargar_vacante():
    with (DATA / "vacantes.json").open("r", encoding="utf-8-sig") as archivo:
        return json.load(archivo)["vacantes"][0]


def ejecutar():
    # Se usa el camino real de ejecución para respetar el recursion_limit (RNF-04).
    return invocar_con_limite(
        crear_estado_inicial(cargar_vacante(), cargar_candidatos()), cargar_configuracion()
    )


# --- RF-09 ---

def test_descarta_duplicados_por_correo():
    validos, duplicados = depurar_duplicados(cargar_candidatos())

    ids_validos = {c["id"] for c in validos}
    ids_duplicados = {d["id"]: d for d in duplicados}

    assert "C032" in ids_duplicados
    assert ids_duplicados["C032"]["conservado_id"] == "C001"
    assert "Mismo correo" in ids_duplicados["C032"]["motivo"]
    assert "C001" in ids_validos


def test_descarta_duplicados_por_nombre_y_telefono():
    _, duplicados = depurar_duplicados(cargar_candidatos())

    ids_duplicados = {d["id"]: d for d in duplicados}

    assert "C031" in ids_duplicados
    assert ids_duplicados["C031"]["conservado_id"] == "C023"
    assert "Mismo correo" in ids_duplicados["C031"]["motivo"]
    assert "nombre y teléfono" in ids_duplicados["C031"]["motivo"]


def test_estado_inicial_sin_eventos_de_auditoria_completos():
    # El estado inicial también cumple el formato de RF-10.
    estado = crear_estado_inicial(cargar_vacante(), cargar_candidatos())

    assert set(estado["auditoria"][0]) == {"iteracion", "nodo", "decision", "motivo"}


def test_conserva_solo_un_perfil_por_persona():
    candidatos = cargar_candidatos()
    validos, duplicados = depurar_duplicados(candidatos)

    # El dataset puede crecer con candidatos que llegan por correo.
    assert len(validos) + len(duplicados) == len(candidatos)
    assert len(duplicados) == 2

    correos = [c["email"].casefold() for c in validos]
    assert len(correos) == len(set(correos))

    personas = {(c["nombre"].casefold(), c["telefono"]) for c in validos}
    assert len(personas) == len(validos)


def test_grafo_usa_solo_candidatos_unicos():
    resultado = ejecutar()

    assert len(resultado["candidatos_filtrados"]) + len(resultado["duplicados"]) == len(
        resultado["candidatos"]
    )
    assert {c["id"] for c in resultado["candidatos_filtrados"]}.isdisjoint(
        {"C031", "C032"}
    )


def test_duplicados_por_variantes_de_escritura():
    candidatos = [
        {"id": "X1", "nombre": "JOSÉ  Pérez", "email": "jose.perez@example.com", "telefono": "8888-0001"},
        {"id": "X2", "nombre": "Jose Perez", "email": "JOSE.PEREZ@example.com", "telefono": "88880001"},
        {"id": "X3", "nombre": "Ana López", "email": "ana@example.com", "telefono": "8888-0001"},
        {"id": "X4", "nombre": "jose  perez", "email": "otro@example.com", "telefono": "8888-0001"},
    ]

    validos, duplicados = depurar_duplicados(candidatos)

    assert [c["id"] for c in validos] == ["X1", "X3"]
    assert {d["id"] for d in duplicados} == {"X2", "X4"}


# --- RF-10 ---

def test_cada_evento_tiene_iteracion_nodo_decision_motivo():
    resultado = ejecutar()

    for evento in resultado["auditoria"]:
        assert set(evento) == {"iteracion", "nodo", "decision", "motivo"}
        assert isinstance(evento["iteracion"], int)
        assert evento["nodo"]
        assert evento["decision"]
        assert evento["motivo"]


def test_decisiones_de_duplicados_quedan_en_auditoria():
    resultado = ejecutar()

    descartes = [
        evento
        for evento in resultado["auditoria"]
        if evento["decision"] == "descartar_duplicado"
    ]

    assert len(descartes) == 2
    assert all(evento["nodo"] == "depurar_duplicados" for evento in descartes)
    assert all("Mismo" in evento["motivo"] for evento in descartes)


def test_iteraciones_avanzan_con_el_loop():
    resultado = ejecutar()

    iteraciones = [
        evento["iteracion"]
        for evento in resultado["auditoria"]
        if evento["nodo"] == "procesar_candidato"
    ]

    total = len(resultado["candidatos_filtrados"])
    # La primera pasada evalúa una vez a cada candidato; las siguientes
    # solo existen si la vacante necesitó relajaciones (RF-06).
    assert iteraciones[:total] == list(range(1, total + 1))
    assert resultado["iteracion"] == len(iteraciones)
    assert len(iteraciones) == total * (len(resultado["relajaciones_aplicadas"]) + 1)
    assert resultado["auditoria"][-1]["decision"] == "finalizar"
    assert any(
        evento["decision"] == "shortlist_generada"
        for evento in resultado["auditoria"]
    )


def test_auditoria_de_error_de_validacion():
    resultado = app_matching.invoke(crear_estado_inicial({}, []))

    assert resultado["estado"] == "error"
    ultimo = resultado["auditoria"][-1]
    assert ultimo["nodo"] == "validar_estado"
    assert ultimo["decision"] == "error"
    assert ultimo["motivo"]
