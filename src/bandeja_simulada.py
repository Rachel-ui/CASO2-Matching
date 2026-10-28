"""Ciclo horario sobre la bandeja simulada de correos (RF-15).

Un ciclo = 1 hora simulada. En cada ciclo el agente:

1. Lee de `data/bandeja.json` los correos que llegaron hasta la hora actual.
2. Ignora los `message_id` que ya procesó (se guardan en
   `data/bandeja_procesados.json`), así un correo nunca se procesa dos veces
   aunque vuelva a aparecer en la bandeja.
3. Corre el matching **solo** si llegó un correo de vacante: ese es el
   disparador del proceso. Los correos de candidato y los desconocidos se
   registran pero no lanzan el matching.

La corrida termina cuando ya no queda ninguna vacante sin leer en la bandeja
(las 24 h solo se agotan si no llega ninguna vacante), o al llegar a la hora
máxima (24 por defecto). Los correos de gestión, candidato o basura que queden
se reportan como "sin leer al cerrar" pero no alargan la corrida.

La bandeja simulada es determinista y avanza con la hora simulada, no con el
reloj real, así que la corrida siempre tarda lo mismo y da el mismo resultado
(RNF-03). El modo `--ritmo-real` agrega una pausa entre ciclos para verlo
avanzar en vivo; no cambia lo que se procesa.
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from src.agentmail_cliente import Correo


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
ARCHIVO_BANDEJA = DATA / "bandeja.json"
ARCHIVO_PROCESADOS = DATA / "bandeja_procesados.json"

# Un ciclo del caso 1 equivale a una hora simulada de monitoreo.
HORAS_POR_CICLO = 1
# Hasta esta hora se siguen leyendo correos (RNF-04: 24 h por corrida).
MAX_HORAS_SIMULADAS = 24


def cargar_bandeja(ruta: Path | None = None) -> dict:
    """Lee la bandeja simulada completa (inicio + correos)."""

    ruta = Path(ruta) if ruta else ARCHIVO_BANDEJA

    with ruta.open("r", encoding="utf-8-sig") as archivo:
        return json.load(archivo)


def cargar_procesados(ruta: Path | None = None) -> list[str]:
    """IDs de los correos ya procesados en corridas anteriores."""

    ruta = Path(ruta) if ruta else ARCHIVO_PROCESADOS
    if not ruta.exists():
        return []

    with ruta.open("r", encoding="utf-8-sig") as archivo:
        datos = json.load(archivo)

    return list(datos.get("procesados", []))


def guardar_procesados(ids: list[str], ruta: Path | None = None) -> Path:
    """Guarda, sin repetir y en orden, los IDs que ya se procesaron."""

    ruta = Path(ruta) if ruta else ARCHIVO_PROCESADOS
    ruta.parent.mkdir(parents=True, exist_ok=True)

    with ruta.open("w", encoding="utf-8") as archivo:
        json.dump({"procesados": list(dict.fromkeys(ids))}, archivo, ensure_ascii=False, indent=2)
        archivo.write("\n")

    return ruta


def correos_hasta_hora(correos: list[dict], inicio, hora: int) -> list[dict]:
    """Correos que llegaron desde `inicio` hasta `inicio + hora` (RF-15)."""

    limite = inicio + timedelta(hours=hora * HORAS_POR_CICLO)
    llegados = []

    for correo in correos:
        try:
            fecha = datetime.fromisoformat(str(correo.get("timestamp") or ""))
        except ValueError:
            continue
        if fecha <= limite:
            llegados.append(correo)

    # Orden estable por hora de llegada: si dos correos caen en la misma hora,
    # se procesan en el orden en que llegaron.
    return sorted(llegados, key=lambda correo: str(correo.get("timestamp") or ""))


def es_vacante(correo: dict) -> bool:
    """Un correo dispara el matching solo si su texto describe una vacante."""

    from src.interpretar_correo_bandeja import clasificar_correo

    return clasificar_correo(correo)["tipo"] == "vacante"


def correo_dominio(datos: dict) -> Correo:
    """Convierte una entrada de la bandeja simulada al tipo `Correo`."""

    return Correo(
        message_id=str(datos.get("message_id") or ""),
        thread_id=str(datos.get("thread_id") or datos.get("message_id") or ""),
        remitente=str(datos.get("remitente") or ""),
        destinatarios=[str(d) for d in (datos.get("destinatarios") or [])],
        asunto=str(datos.get("asunto") or ""),
        fecha=str(datos.get("timestamp") or ""),
        cuerpo=str(datos.get("cuerpo") or ""),
    )


def procesar_correo_bandeja(
    correo: dict,
    vacantes: list[dict],
    estado_simulado: dict,
    cola: dict | None = None,
    modo: str | None = None,
) -> dict:
    """Procesa un correo simulado y devuelve qué hizo con él (RF-15/RF-16).

    Delega en `src.interpretar_correo_bandeja` para no tocar el dataset real.
    """

    from src.interpretar_correo_bandeja import procesar_correo

    return procesar_correo(correo, vacantes, estado_simulado, cola=cola, modo=modo)


def ejecutar_bandeja(
    hora_maxima: int = MAX_HORAS_SIMULADAS,
    ruta_bandeja: Path | None = None,
    ruta_procesados: Path | None = None,
    reiniciar: bool = False,
    pausa: float = 0.0,
    al_avanzar=None,
) -> dict:
    """Corre la bandeja hora simulada por hora hasta la hora máxima.

    Devuelve el resumen de la corrida: ciclos, correos leídos, disparos de
    matching, vacantes en cola y el motivo por el que terminó.
    """

    from datetime import datetime

    bandeja = cargar_bandeja(ruta_bandeja)
    inicio = datetime.fromisoformat(bandeja["inicio"])
    correos = bandeja.get("correos", [])

    from src.clasificar_correos import guardar_cola, vacia_cola

    procesados = [] if reiniciar else cargar_procesados(ruta_procesados)
    # Cola de vacantes de la corrida (RF-16): solo una vacante nueva entra y
    # dispara el matching; queda en data/cola_vacantes.json para el reporte.
    cola = vacia_cola()
    if reiniciar:
        guardar_cola(cola)
    hora_maxima = min(hora_maxima, MAX_HORAS_SIMULADAS)
    ciclos = []
    motivo_fin = "hora_maxima"
    # Catálogo y resultados de la simulación: viven solo en esta corrida, para
    # no modificar data/ ni contar dos veces a un candidato.
    vacantes: list[dict] = []
    estado_simulado: dict = {}

    # Correos de la bandeja aún no leídos. Solo los correos de vacante cuentan
    # para cerrar la corrida: los de gestión, candidato o basura se registran
    # pero no justifican seguir leyendo la bandeja (el caso 1 despacha todo en
    # 3-4 h, sin esperar las 24 h; RF-15).
    def _vacantes_sin_leer() -> list[dict]:
        return [
            c
            for c in correos
            if str(c.get("message_id")) not in procesados
            and isinstance(c.get("vacante_estructurada"), dict)
            and c["vacante_estructurada"].get("id")
        ]

    for hora in range(1, hora_maxima + 1):
        llegados = correos_hasta_hora(correos, inicio, hora)
        # Se compara contra lo que había al abrir el ciclo (`procesados`), no
        # contra lo que se procesa dentro de él.
        sin_procesar = [c for c in llegados if str(c.get("message_id")) not in procesados]
        nuevos = list(sin_procesar)

        ciclo = {
            "hora": hora,
            "hora_simulada": _hora_texto(inicio, hora),
            "correos_nuevos": [str(c.get("message_id")) for c in nuevos],
            "acciones": [],
            "matching_disparado": [],
            # Vacantes que ocuparían la cola al cerrar el ciclo. Cada vacante
            # dispara su matching en el mismo ciclo en que llega, así que la
            # cola queda vacía salvo que un matching haya fallado.
            "vacantes_en_cola": [],
        }

        for correo in nuevos:
            accion = procesar_correo_bandeja(correo, vacantes, estado_simulado, cola=cola)
            ciclo["acciones"].append(
                {
                    "message_id": accion["message_id"],
                    "accion": accion["accion"],
                    "vacante_id": accion["vacante_id"],
                    "errores": accion["errores"],
                }
            )
            if accion["disparo_matching"]:
                ciclo["matching_disparado"].append(accion["vacante_id"])
            elif accion["vacante_id"] and accion["accion"] == "revision_humana":
                ciclo["vacantes_en_cola"].append(accion["vacante_id"])
            procesados.append(accion["message_id"])

        # Los IDs se guardan al cerrar cada ciclo: si la corrida se corta, lo
        # ya procesado no se repite en la siguiente corrida (RF-15).
        guardar_procesados(procesados, ruta_procesados)
        ciclos.append(ciclo)

        if al_avanzar is not None:
            al_avanzar(ciclo)
        if pausa:
            time.sleep(pausa)

        if len(llegados) >= len(correos) or not _vacantes_sin_leer():
            motivo_fin = "bandeja_agotada"
            break

    pendientes = [c for c in correos if str(c.get("message_id")) not in procesados]

    return {
        "inicio": bandeja.get("inicio", ""),
        "hora_maxima": hora_maxima,
        "ciclos": ciclos,
        "ciclos_ejecutados": len(ciclos),
        "correos_procesados": procesados,
        "correos_pendientes": [str(c.get("message_id")) for c in pendientes],
        "matching_disparado": [v for ciclo in ciclos for v in ciclo["matching_disparado"]],
        "vacantes": [v.get("id", "") for v in vacantes],
        "vacantes_en_cola": [
            v for ciclo in ciclos for v in ciclo["vacantes_en_cola"]
        ],
        "resultados": {
            clave.removeprefix("salida_"): resultado
            for clave, resultado in estado_simulado.items()
        },
        "motivo_fin": motivo_fin,
        "clasificacion": {
            "vacantes_nuevas": [v.get("id", "") for v in vacantes],
            "duplicados": cola["duplicados"],
            "revision_humana": cola["revision_humana"],
        },
    }


def _hora_texto(inicio, hora: int) -> str:
    return (inicio + timedelta(hours=hora * HORAS_POR_CICLO)).isoformat(timespec="minutes")


def main() -> int:
    import argparse
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Lee la bandeja simulada hora por hora y dispara el matching (RF-15)."
    )
    parser.add_argument(
        "--horas",
        type=int,
        default=MAX_HORAS_SIMULADAS,
        help=f"Horas simuladas de la corrida (máximo {MAX_HORAS_SIMULADAS}).",
    )
    parser.add_argument(
        "--reiniciar",
        action="store_true",
        help="Olvida los correos ya procesados y vuelve a empezar la bandeja.",
    )
    parser.add_argument(
        "--ritmo-real",
        type=float,
        default=0.0,
        metavar="SEGUNDOS",
        help="Pausa entre ciclos para ver la corrida en vivo (no cambia lo procesado).",
    )
    argumentos = parser.parse_args()

    print(
        f"Control de reenvíos: los correos ya procesados se guardan en "
        f"{ARCHIVO_PROCESADOS.name} y una vacante ya guardada no vuelve a "
        f"disparar el matching."
    )

    def mostrar(ciclo: dict) -> None:
        print(
            f"[{ciclo['hora_simulada']}] hora {ciclo['hora']}: "
            f"{len(ciclo['correos_nuevos'])} correo(s) nuevo(s)"
        )
        for accion in ciclo["acciones"]:
            print(f"   {accion['message_id']}: {accion['accion']}")
        if ciclo["matching_disparado"]:
            print(f"   matching disparado: {', '.join(ciclo['matching_disparado'])}")
        else:
            print("   sin vacante: no se dispara el matching")

    resultado = ejecutar_bandeja(
        hora_maxima=argumentos.horas,
        reiniciar=argumentos.reiniciar,
        pausa=argumentos.ritmo_real,
        al_avanzar=mostrar,
    )

    print(
        f"\nCiclos ejecutados: {resultado['ciclos_ejecutados']} "
        f"(hora máxima {resultado['hora_maxima']} h simuladas; RNF-04 permite {MAX_HORAS_SIMULADAS} h)"
    )
    print(f"Correos procesados: {len(resultado['correos_procesados'])}")
    print(f"Matchings disparados: {', '.join(resultado['matching_disparado']) or 'ninguno'}")
    print(f"Vacantes procesadas: {', '.join(resultado['vacantes']) or 'ninguna'}")
    print(f"Vacantes en cola al terminar: {len(resultado['vacantes_en_cola'])}")
    clasificacion = resultado["clasificacion"]
    print(
        "Clasificación (RF-16): "
        f"{len(clasificacion['vacantes_nuevas'])} vacante(s) nueva(s), "
        f"{len(clasificacion['duplicados'])} duplicado(s), "
        f"{len(clasificacion['revision_humana'])} para revisión humana"
    )
    for duplicado in clasificacion["duplicados"]:
        print(
            f"   {duplicado['message_id']}: duplicado de "
            f"{duplicado['original_message_id'] or duplicado['vacante_id']}"
        )
    for revision in clasificacion["revision_humana"]:
        print(f"   {revision['message_id']}: revisión humana - {revision['motivo']}")
    for vacante_id, estado in resultado["resultados"].items():
        print(
            f"   {vacante_id}: {estado['estado']}, {len(estado['shortlist'])} en shortlist, "
            f"{estado.get('pasos_grafo', 0)} pasos"
        )
    print(f"Correos sin leer al cerrar: {', '.join(resultado['correos_pendientes']) or 'ninguno'}")
    print(f"La corrida terminó por: {resultado['motivo_fin']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
