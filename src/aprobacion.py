
"""Aprobación humana de la shortlist antes de cerrar (RF-08).

El grafo se detiene en el nodo `aprobacion_humana` con el `interrupt` de
LangGraph y muestra la shortlist. La persona rechaza a los candidatos que no
quiere (o aprueba todo) y, por cada rechazado, el agente lo excluye y busca un
reemplazo entre los perfiles aptos restantes. La shortlist nueva se vuelve a
presentar hasta que se apruebe o se alcance `approval.max_reviews`.

La corrida automática (`ejecutar_matching`, bandeja y reportes) no se detiene:
su ronda de aprobación queda registrada en la auditoría sin bloquear el
proceso. Este módulo es el que sí espera a una persona.

Uso:

    python -m src.aprobacion V001
    python -m src.aprobacion V001 --rechazar C004,C011
    python -m src.aprobacion V001 --aprobar-todo

Con `--rechazar` las respuestas se aplican en orden (una ronda por rechazo);
sin `--rechazar` se preguntan por consola en cada ronda.
"""

import argparse
import sys
import json
import uuid
from pathlib import Path

from langgraph.types import Command

from src.configuracion import cargar_configuracion
from src.estado_agente import crear_estado_inicial
from src.grafo_matching import compilar_con_aprobacion


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


def _bloques_pendientes(instantanea: dict) -> list[dict]:
    """Payloads de los `interrupt` que dejó la corrida al detenerse.

    Los `interrupt` llegan bajo la clave `__interrupt__` del resultado; si esa
    clave no está, se buscan en las tareas pendientes de la instantánea.
    """

    pendientes = instantanea.get("__interrupt__") or ()
    if pendientes:
        return [paso.value for paso in pendientes]

    return [
        tarea.interrupts[0].value
        for tarea in instantanea.get("tasks", ())
        if getattr(tarea, "interrupts", None)
    ]


def _mostrar_shortlist(payload: dict) -> None:
    print(
        f"\nAprobación humana (RF-08) - vacante {payload.get('vacante_id', '')}, "
        f"revisión {payload.get('revision', 1)}/{payload.get('limite_revisiones', 3)}"
    )
    if payload.get("rechazados_previos"):
        print(f"  Ya rechazados: {', '.join(payload['rechazados_previos'])}")
    print(f"  {payload.get('mensaje', '')}")
    for item in payload.get("shortlist", ()):
        print(
            f"  {item['posicion']}. {item['id']} - {item['puntaje']:g} puntos "
            f"({'cumple requisitos' if item['cumple_requisitos'] else 'no cumple'})"
        )
        print(f"     {item['justificacion']}")
    reemplazos = payload.get("reemplazos_disponibles") or []
    if reemplazos:
        print(
            "  Reemplazos disponibles si rechaza a alguien: "
            + ", ".join(f"{r['id']} ({r['puntaje']:g})" for r in reemplazos)
        )


def _leer_rechazos(payload: dict) -> list[str]:
    """Pregunta por consola qué IDs se rechazan (ENTER = aprobar todo)."""

    ids = [item["id"] for item in payload.get("shortlist", ())]
    try:
        entrada = input("\nIDs a rechazar (separados por coma, ENTER = aprobar todo): ")
    except (EOFError, OSError):  # corrida no interactiva: se aprueba
        return []
    return [cid.strip() for cid in entrada.split(",") if cid.strip() in ids]


def aprobar_shortlist(
    vacante_id: str = "V001",
    rechazos: list[list[str]] | None = None,
    interactivo: bool = True,
    ruta_salida: Path | None = None,
) -> dict:
    """Corre el matching y lo detiene para la aprobación humana (RF-08).

    `rechazos` son las respuestas humanas, una lista de IDs por ronda; si se
    acaban, las rondas siguientes se aprueban. `interactivo` pregunta por
    consola cuando no hay rechazos programados.
    """

    from src.ejecutar_matching import cargar_candidatos, cargar_vacante

    config = cargar_configuracion()
    estado_inicial = crear_estado_inicial(cargar_vacante(vacante_id), cargar_candidatos())
    # RF-08: esta corrida sí espera a una persona en el interrupt.
    estado_inicial["interrupt_habilitado"] = True
    grafo = compilar_con_aprobacion()
    hilo = {"configurable": {"thread_id": f"aprobacion-{uuid.uuid4().hex[:8]}"}}

    resultado = grafo.invoke(
        estado_inicial, {**hilo, "recursion_limit": config.recursion_limit}
    )
    respuestas = list(rechazos or [])

    while True:
        pendientes = _bloques_pendientes(resultado)
        if not pendientes:
            break

        payload = pendientes[0]
        _mostrar_shortlist(payload)

        if respuestas:
            # Respuesta programada (CLI o pruebas): se aplica sin preguntar.
            rechazar = respuestas.pop(0)
        elif interactivo:
            rechazar = _leer_rechazos(payload)
        else:
            rechazar = []

        # Vacío = aprobar todo, que es lo que el interrupt interpreta al reanudar.
        resultado = grafo.invoke(Command(resume=rechazar), hilo)

    if ruta_salida is not None:
        ruta_salida.parent.mkdir(parents=True, exist_ok=True)
        with ruta_salida.open("w", encoding="utf-8") as archivo:
            json.dump(
                {
                    "vacante_id": vacante_id,
                    "aprobacion": resultado.get("aprobacion", {}),
                    "shortlist": [
                        {
                            "posicion": item["posicion"],
                            "id": item["id"],
                            "puntaje": item["puntaje"],
                            "justificacion": item["justificacion"],
                        }
                        for item in resultado["shortlist"]
                    ],
                },
                archivo,
                ensure_ascii=False,
                indent=2,
            )
            archivo.write("\n")

    return resultado


def resumen_aprobacion(resultado: dict) -> list[str]:
    """Líneas para la consola con la shortlist final y lo que hizo el humano."""

    aprobacion = resultado.get("aprobacion") or {}
    lineas = [
        f"Estado de aprobación: {aprobacion.get('estado', 'no solicitada')} "
        f"(revisiones: {aprobacion.get('revisiones', 0)})",
        f"Rechazados: {', '.join(aprobacion.get('rechazados') or []) or 'ninguno'}",
        "Shortlist final:",
    ]
    for item in resultado["shortlist"]:
        reemplazo = f" (reemplaza a {item['reemplaza_a']})" if item.get("reemplaza_a") else ""
        lineas.append(f"  {item['posicion']}. {item['id']} - {item['puntaje']:g} puntos{reemplazo}")
    sin_reemplazo = aprobacion.get("puestos_sin_reemplazo") or 0
    if sin_reemplazo:
        lineas.append(
            f"Puestos sin cubrir por rechazos sin reemplazo: {sin_reemplazo} "
            "(la vacante queda para revisión humana)."
        )
    return lineas


if __name__ == "__main__":
    # La consola de Windows abre en cp1252: la shortlist trae acentos.
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Aprobación humana de la shortlist (RF-08).")
    parser.add_argument("vacante", nargs="?", default="V001", help="ID de la vacante")
    parser.add_argument(
        "--rechazar",
        default="",
        help="IDs a rechazar, en orden y separados por coma (una ronda por ID)",
    )
    parser.add_argument(
        "--aprobar-todo",
        action="store_true",
        help="No pregunta: aprueba la shortlist sin rechazar a nadie",
    )
    parser.add_argument(
        "--salida",
        default="",
        help="Archivo JSON opcional con la aprobación y la shortlist final",
    )
    argumentos = parser.parse_args()

    rechazos = []
    for cid in [c.strip() for c in argumentos.rechazar.split(",") if c.strip()]:
        rechazos.append([cid])

    resultado = aprobar_shortlist(
        argumentos.vacante,
        rechazos=rechazos,
        # Con rechazos programados se aplican tal cual y el resto se aprueba.
        interactivo=not argumentos.aprobar_todo and not rechazos,
        ruta_salida=Path(argumentos.salida) if argumentos.salida else None,
    )

    print()
    for linea in resumen_aprobacion(resultado):
        print(linea)
