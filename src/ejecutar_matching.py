
"""Ejecuta el agente de matching y exporta shortlist y auditoría.

Cubre RF-09, RF-10, RNF-02, RNF-03 y RNF-05.
"""

import csv
import json
import time
from pathlib import Path

from src.estado_agente import crear_estado_inicial
from src.grafo_matching import app_matching


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
REPORTS = RAIZ / "reports"

CAMPOS_AUDITORIA = ("iteracion", "nodo", "decision", "motivo")
CAMPOS_SHORTLIST = (
    "posicion",
    "id",
    "puntaje",
    "supera_umbral",
    "cumple_requisitos",
    "mandatory_skills",
    "desirable_skills",
    "experience",
    "english",
    "availability",
    "justificacion",
)


def cargar_vacante(vacante_id: str) -> dict:
    with (DATA / "vacantes.json").open("r", encoding="utf-8-sig") as archivo:
        vacantes = json.load(archivo)["vacantes"]

    for vacante in vacantes:
        if vacante.get("id") == vacante_id:
            return vacante

    raise ValueError(f"No se encontró la vacante {vacante_id}.")


def cargar_candidatos() -> list[dict]:
    with (DATA / "candidatos.csv").open("r", encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def exportar_auditoria(auditoria: list[dict], ruta: Path) -> None:
    """Guarda el log de auditoría en CSV con las cuatro columnas de RF-10."""

    ruta.parent.mkdir(parents=True, exist_ok=True)

    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=CAMPOS_AUDITORIA)
        escritor.writeheader()
        for evento in auditoria:
            escritor.writerow({campo: evento.get(campo, "") for campo in CAMPOS_AUDITORIA})


def exportar_shortlist(shortlist: list[dict], ruta: Path) -> None:
    """Guarda la shortlist en CSV con puntaje, criterios y justificación."""

    ruta.parent.mkdir(parents=True, exist_ok=True)

    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=CAMPOS_SHORTLIST)
        escritor.writeheader()
        for item in shortlist:
            fila = {campo: item.get(campo, "") for campo in CAMPOS_SHORTLIST}
            fila.update(item.get("criterios", {}))
            escritor.writerow(fila)


def resumen_resultado(resultado: dict) -> dict:
    """Resume el resultado de una vacante: éxito, relajaciones y consultas (RF-04/05/06)."""

    vacante = resultado["vacante_actual"]
    vacante_original = resultado.get("vacante_original") or vacante

    return {
        "vacante_id": vacante.get("id", ""),
        "titulo": vacante.get("titulo", ""),
        "escenario": vacante.get("scenario", ""),
        "estado": resultado["estado"],
        "exito": bool((resultado.get("evaluacion") or {}).get("exito")),
        "aptos": (resultado.get("evaluacion") or {}).get("aptos", 0),
        "minimo": (resultado.get("evaluacion") or {}).get("minimo", 0),
        "shortlist": len(resultado["shortlist"]),
        "requiere_revision_humana": resultado["requiere_revision_humana"],
        "relajaciones": [r["descripcion"] for r in resultado["relajaciones_aplicadas"]],
        "consultas_reclutador": [
            c for c in resultado["consultas_reclutador"]
            if c.get("resultado") != "no_requiere"
        ],
        "criterios_vigentes": {
            campo: vacante.get(campo)
            for campo in (
                "skills_obligatorios",
                "experience_required",
                "english_required",
                "availability_required",
                "modality",
            )
        },
        "criterios_originales": {
            campo: vacante_original.get(campo)
            for campo in (
                "experience_required",
                "english_required",
                "availability_required",
            )
        },
    }


def ejecutar_vacante(vacante_id: str = "V001") -> dict:
    """Ejecuta el agente para una vacante y devuelve el estado final."""

    vacante = cargar_vacante(vacante_id)
    candidatos = cargar_candidatos()

    estado_inicial = crear_estado_inicial(vacante, candidatos)
    return app_matching.invoke(estado_inicial)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ejecuta el agente de matching.")
    parser.add_argument("vacante", nargs="?", default="V001", help="ID de la vacante")
    parser.add_argument(
        "--salida",
        default="data/salida.json",
        help="Archivo donde el agente deja la respuesta (RF-17)",
    )
    argumentos = parser.parse_args()

    inicio = time.perf_counter()
    try:
        resultado = ejecutar_vacante(argumentos.vacante)
    except (ValueError, OSError) as error:
        raise SystemExit(f"Error: {error}")
    duracion = time.perf_counter() - inicio

    vacante_id = resultado["vacante_actual"]["id"]
    ruta_log = REPORTS / f"auditoria_{vacante_id}.csv"
    ruta_shortlist = REPORTS / f"shortlist_{vacante_id}.csv"

    exportar_auditoria(resultado["auditoria"], ruta_log)
    exportar_shortlist(resultado["shortlist"], ruta_shortlist)

    resumen = resumen_resultado(resultado)
    ruta_salida = Path(argumentos.salida)
    if not ruta_salida.is_absolute():
        ruta_salida = RAIZ / ruta_salida
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    with ruta_salida.open("w", encoding="utf-8") as archivo:
        json.dump(resumen, archivo, ensure_ascii=False, indent=2)
        archivo.write("\n")

    print(f"Modo: {resultado['configuracion'].modo}")
    print(f"Vacante: {vacante_id} ({resumen['escenario']})")
    print(f"Candidatos leídos: {len(resultado['candidatos'])}")
    print(f"Candidatos únicos: {len(resultado['candidatos_filtrados'])}")
    print(f"Duplicados descartados: {len(resultado['duplicados'])}")
    print(f"Consultas al reclutador: {len(resumen['consultas_reclutador'])}")
    print(f"Llamadas al LLM: {resultado['llm_calls']}")
    print(f"Eventos de auditoría: {len(resultado['auditoria'])}")
    print(f"Tiempo de procesamiento: {duracion:.3f} s")

    if resumen["exito"]:
        print(
            f"\nResultado (RF-05): ÉXITO - {resumen['aptos']} candidatos superan el "
            f"umbral (mínimo {resumen['minimo']}), {resumen['shortlist']} en la shortlist."
        )
    else:
        print(
            f"\nResultado (RF-05): SIN ÉXITO - solo {resumen['aptos']} candidatos "
            f"superan el umbral (mínimo {resumen['minimo']})."
        )
    for descripcion in resumen["relajaciones"]:
        print(f"  relajación: {descripcion}")
    if resumen["requiere_revision_humana"]:
        if resumen["exito"]:
            print(
                "La condición de éxito se cumplió, pero quedan puestos sin cubrir: "
                "la vacante va a revisión humana."
            )
        else:
            print("La vacante queda INCOMPLETA y requiere revisión humana.")

    print("\nShortlist:")
    for item in resultado["shortlist"]:
        print(f"{item['posicion']}. {item['id']} - {item['puntaje']:g} puntos")
        print(f"   {item['justificacion']}")

    print(f"\nLog guardado en: {ruta_log}")
    print(f"Shortlist guardada en: {ruta_shortlist}")
    print(f"Salida del agente: {ruta_salida}")
