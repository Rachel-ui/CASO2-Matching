
"""Procesa un correo de la bandeja: guarda la vacante y ejecuta el matching.

Flujo (RF-01 + RF-09 + RF-10):
1. Extrae la vacante del cuerpo o del adjunto y la valida.
2. La guarda en `data/vacantes.json` (sin duplicar el ID).
3. Corre el agente de matching y deja shortlist y auditoría en `reports/`.

El correo original no genera archivos aparte: se registra en
`data/correos_recibidos.csv`.
"""

import json
from datetime import datetime
from pathlib import Path

from src.agentmail_cliente import AgentMailCliente, Correo
from src.configuracion import cargar_configuracion
from src.ejecutar_matching import invocar_con_limite, texto_limites
from src.grafo_matching import app_matching
from src.solicitud_vacante import ErrorVacante, SolicitudVacante, extraer_vacante


RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
REPORTS = RAIZ / "reports"
ARCHIVO_VACANTES = DATA / "vacantes.json"


def _leer_vacantes() -> list[dict]:
    with ARCHIVO_VACANTES.open("r", encoding="utf-8-sig") as archivo:
        return json.load(archivo).get("vacantes", [])


def guardar_vacante(vacante: dict, correo: Correo, origen: str) -> str:
    """Agrega o actualiza la vacante en el catálogo único `data/vacantes.json`.

    No se crea un archivo por vacante: el correo que la pidió queda en
    `data/correos_recibidos.csv`.
    """

    vacantes = _leer_vacantes()
    identificador = vacante["id"]

    actual = next((v for v in vacantes if v.get("id") == identificador), None)
    if actual is not None and actual == vacante:
        # Reenvío de una vacante ya guardada: no se modifica ni se reprocesa.
        print(f"Vacante {identificador} ya estaba en {ARCHIVO_VACANTES.name} ({origen}).")
        return "sin_cambios"

    if actual is not None:
        vacantes = [v for v in vacantes if v.get("id") != identificador]
        accion = "actualizada"
    else:
        accion = "agregada"

    vacantes.append(vacante)

    ARCHIVO_VACANTES.parent.mkdir(parents=True, exist_ok=True)
    with ARCHIVO_VACANTES.open("w", encoding="utf-8") as archivo:
        json.dump({"vacantes": vacantes}, archivo, ensure_ascii=False, indent=2)
        archivo.write("\n")

    print(f"Vacante {identificador} {accion} en {ARCHIVO_VACANTES.name} ({origen}).")

    return accion


def cargar_candidatos() -> list[dict]:
    import csv

    with (DATA / "candidatos.csv").open("r", encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def procesar_correo(
    correo: Correo,
    cliente: AgentMailCliente | None = None,
    vacante: dict | None = None,
) -> dict:
    """Convierte el correo en vacante, la guarda y ejecuta el matching.

    Si el correo no trae un JSON, el texto libre se interpreta primero
    (src/interpretar_texto.py) para extraer los campos de la vacante.
    `vacante` permite entregar la vacante ya estructurada (bandeja simulada).
    """

    descargar = cliente.descargar_adjunto if cliente is not None else None

    try:
        solicitud = extraer_vacante(
            correo, descargar_adjunto=descargar, vacante_estructurada=vacante
        )
    except ErrorVacante as error:
        from src.interpretar_texto import TIPO_VACANTE, interpretar

        interpretado = interpretar(correo.cuerpo)
        datos = interpretado.datos

        # Solo se usa el texto libre si aporta datos de una vacante.
        aporta_datos = bool(
            datos.get("skills_obligatorios")
            or datos.get("experience_required") is not None
            or datos.get("english_required")
        )
        if interpretado.tipo != TIPO_VACANTE or not aporta_datos:
            raise

        print(f"Aviso: {error}")
        print("Se interpretó el texto libre del correo como vacante:")
        for campo, valor in interpretado.datos.items():
            if valor not in ("", None, [], {}):
                print(f"  {campo}: {valor}")
        for advertencia in interpretado.advertencias:
            print(f"  aviso: {advertencia}")

        solicitud = SolicitudVacante(
            {**datos, "id": "V" + datetime.now().strftime("%Y%m%d%H%M%S")},
            "texto libre del correo",
            correo,
            interpretado.advertencias,
        )

    for advertencia in solicitud.advertencias:
        print(f"Aviso: {advertencia}")

    guardar_vacante(solicitud.vacante, correo, solicitud.origen)

    from src.estado_agente import crear_estado_inicial

    estado_inicial = crear_estado_inicial(solicitud.vacante, cargar_candidatos())
    config = cargar_configuracion()
    resultado = invocar_con_limite(estado_inicial, config)

    # Se resuelven en el momento (no al importar) para que REPORTS se pueda
    # redirigir en las pruebas.
    from src.ejecutar_matching import exportar_auditoria, exportar_shortlist

    vacante_id = solicitud.vacante["id"]
    ruta_log = REPORTS / f"auditoria_{vacante_id}.csv"
    ruta_shortlist = REPORTS / f"shortlist_{vacante_id}.csv"
    exportar_auditoria(resultado["auditoria"], ruta_log)
    exportar_shortlist(resultado["shortlist"], ruta_shortlist)

    return {
        "vacante": solicitud.vacante,
        "resultado": resultado,
        "ruta_auditoria": ruta_log,
        "ruta_shortlist": ruta_shortlist,
    }


def mostrar_resultado(procesado: dict) -> None:
    vacante = procesado["vacante"]
    resultado = procesado["resultado"]
    shortlist = resultado["shortlist"]

    print(f"\nVacante {vacante['id']}: {vacante['titulo']}")
    print(f"Candidatos únicos evaluados: {len(resultado['candidatos_filtrados'])}")
    print(f"Duplicados descartados: {len(resultado['duplicados'])}")

    print(texto_limites(resultado.get("limites", {}), resultado.get("pasos_grafo", 0)))

    if not shortlist:
        print("\nNingún candidato cumplió todos los requisitos y el umbral.")
    else:
        print(f"\nShortlist ({len(shortlist)}):")
        for item in shortlist:
            print(
                f"{item['posicion']}. {item['id']} - {item['puntaje']:g} puntos"
                f" ({'cumple' if item['cumple_requisitos'] else 'no cumple'} requisitos)"
            )
            print(f"   {item['justificacion']}")

    # Shortlist parcial: se entrega lo que hay y se explica el bloqueo (RF-07).
    analisis = resultado.get("analisis_shortlist") or {}
    if analisis.get("puestos_libres"):
        print(
            f"\nShortlist parcial (RF-07): {analisis['puestos_llenos']} de "
            f"{analisis['puestos_llenos'] + analisis['puestos_libres']} puestos. "
            f"Requisito que impide completarla: {analisis.get('requisito_principal', '')}. "
            f"{analisis.get('motivo_principal', '')}"
        )
        for bloque in analisis.get("bloqueantes", []):
            print(
                f"  - {bloque['requisito']} ({len(bloque['casos'])} perfiles): "
                f"{'; '.join(bloque['casos'])}"
            )

    print(f"\nAuditoría: {procesado['ruta_auditoria']}")
    print(f"Shortlist: {procesado['ruta_shortlist']}")


def procesar_correo_nuevo(correo: Correo, cliente: AgentMailCliente | None = None) -> int:
    """Punto de entrada del modo continuo: un error no detiene la vigilancia.

    El grafo `app_correo` decide si el correo describe una vacante o un
    candidato, lo ordena y lo guarda.
    """

    from src.grafo_correo import interpretar_y_guardar

    estado = interpretar_y_guardar(correo.cuerpo, correo, cliente)

    for evento in estado.get("auditoria", []):
        print(f"  [{evento['nodo']}] {evento['motivo']}")

    accion = estado.get("accion")

    if accion == "vacante_guardada":
        mostrar_resultado(estado["resultado"])
        return 0

    if accion == "candidato_guardado":
        candidato = estado["resultado"]["candidato"]
        print(f"\nCandidato {candidato['id']}: {candidato.get('nombre') or '(sin nombre)'}")
        print(f"  Skills: {candidato.get('skills') or '(sin skills)'}")
        print(f"  Experiencia: {candidato.get('experience_years') or 'sin dato'}")
        print(f"  Inglés: {candidato.get('english_level') or 'sin dato'}")
        print(f"  Modalidad: {candidato.get('modality') or 'sin dato'}")
        print(f"  Rol: {candidato.get('rol') or 'sin dato'}")
        for advertencia in estado.get("advertencias", []):
            print(f"  aviso: {advertencia}")
        print("Ya queda disponible para los próximos matchings.")
        return 0

    if accion == "revision_humana":
        print(f"\nEl correo describe una vacante pero está incompleta; requiere revisión.")
        return 1

    if accion == "descartado":
        print(f"\nCorreo {correo.message_id} descartado: no pedía vacante ni describía un candidato.")
        return 1

    for error in estado.get("errores", []):
        print(f"Error al procesar {correo.message_id}: {error}")
    return 1
