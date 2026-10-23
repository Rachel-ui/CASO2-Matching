
"""Registro CSV de los correos procesados desde AgentMail.

Guardar el texto original junto con la interpretación permite comprobar
después si la clasificación (vacante / candidato / desconocido) fue correcta.
No se guardan credenciales ni claves (RNF-09).
"""

import csv
from datetime import datetime
from pathlib import Path

from src.agentmail_cliente import Correo
from src.interpretar_texto import TextoInterpretado, _senales_contexto


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
ARCHIVO_CORREOS = DATA / "correos_recibidos.csv"

CAMPOS = (
    "fecha_proceso",
    "message_id",
    "remitente",
    "asunto",
    "texto",
    "tipo_detectado",
    "tipo_verificado",
    "coincide",
    "senales_detectadas",
    "advertencias",
    "accion",
    "id_generado",
)


def _leer_registro() -> list[dict]:
    if not ARCHIVO_CORREOS.exists():
        return []

    with ARCHIVO_CORREOS.open("r", encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def _señales_legibles(interpretado: TextoInterpretado) -> str:
    evidencia = interpretado.evidencia or _senales_contexto(interpretado.datos.get("descripcion", ""))
    partes = []
    for grupo, oraciones in evidencia.items():
        if oraciones:
            fragmento = " / ".join(str(o)[:80] for o in oraciones[:2])
            partes.append(f"{grupo}: {fragmento}")
    return " | ".join(partes)


def registrar_correo(
    correo: Correo,
    interpretado: TextoInterpretado,
    accion: str = "",
    identificador: str = "",
    tipo_verificado: str = "",
) -> Path:
    """Agrega una fila al registro; si el correo ya está, actualiza la verificación."""

    filas = _leer_registro()
    coincide = ""
    if tipo_verificado:
        coincide = "sí" if tipo_verificado == interpretado.tipo else "no"

    fila = {
        "fecha_proceso": datetime.now().isoformat(timespec="seconds"),
        "message_id": correo.message_id,
        "remitente": correo.remitente,
        "asunto": correo.asunto,
        "texto": (correo.cuerpo or "").replace("\n", " ").strip(),
        "tipo_detectado": interpretado.tipo,
        "tipo_verificado": tipo_verificado,
        "coincide": coincide,
        "senales_detectadas": _señales_legibles(interpretado),
        "advertencias": "; ".join(interpretado.advertencias),
        "accion": accion,
        "id_generado": identificador,
    }

    existente = next(
        (indice for indice, actual in enumerate(filas) if actual["message_id"] == correo.message_id),
        None,
    )
    if existente is None:
        filas.append(fila)
    else:
        filas[existente] = {**filas[existente], **{k: v for k, v in fila.items() if v or k == "tipo_verificado"}}

    ARCHIVO_CORREOS.parent.mkdir(parents=True, exist_ok=True)
    with ARCHIVO_CORREOS.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=CAMPOS)
        escritor.writeheader()
        for actual in filas:
            escritor.writerow({campo: actual.get(campo, "") for campo in CAMPOS})

    return ARCHIVO_CORREOS
