
"""Guarda candidatos que llegan por correo y los agrega al dataset.

El esquema es el mismo de `data/candidatos.csv` (RF-01). Los datos que no
vienen en el correo se guardan vacíos; `validar_dataset.py` los reportará en
vez de inventarlos. El correo original queda registrado en
`data/correos_recibidos.csv`, no en un archivo por candidato.
"""

import csv
from pathlib import Path

from src.agentmail_cliente import Correo


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
ARCHIVO_CANDIDATOS = DATA / "candidatos.csv"

CAMPOS = (
    "id",
    "nombre",
    "email",
    "skills",
    "experience_years",
    "english_level",
    "availability_date",
    "modality",
    "rol",
    "telefono",
)


def leer_candidatos() -> list[dict]:
    if not ARCHIVO_CANDIDATOS.exists():
        return []

    with ARCHIVO_CANDIDATOS.open("r", encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def siguiente_id_candidato() -> str:
    """Siguiente ID correlativo C0NN a partir del máximo existente."""

    numeros = [
        int(fila["id"][1:])
        for fila in leer_candidatos()
        if str(fila.get("id", "")).startswith("C") and fila["id"][1:].isdigit()
    ]
    return f"C{(max(numeros) if numeros else 0) + 1:03d}"


def guardar_candidato(candidato: dict, correo: Correo, origen: str) -> str:
    """Agrega o actualiza el candidato en el CSV (sin crear archivos por correo).

    El texto del correo y su trazabilidad quedan en data/correos_recibidos.csv.
    """

    filas = leer_candidatos()
    identificador = candidato["id"]

    reemplazado = False
    for indice, fila in enumerate(filas):
        if fila.get("id") == identificador:
            filas[indice] = {**fila, **{k: v for k, v in candidato.items() if v not in ("", None)}}
            reemplazado = True
            break

    if not reemplazado:
        filas.append({campo: candidato.get(campo, "") for campo in CAMPOS})

    ARCHIVO_CANDIDATOS.parent.mkdir(parents=True, exist_ok=True)
    with ARCHIVO_CANDIDATOS.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=CAMPOS)
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({campo: fila.get(campo, "") for campo in CAMPOS})

    estado = "actualizado" if reemplazado else "agregado"
    print(f"Candidato {identificador} {estado} en {ARCHIVO_CANDIDATOS.name} ({origen}).")
    return estado
