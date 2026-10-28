"""Reporte por vacante: shortlist, puntajes, relajaciones y supuestos (RF-11).

Un reporte por vacante en Markdown (`reports/reporte_<id>.md`) y un resumen
en JSON (`reports/reporte_<id>.json`) con:

- **Shortlist**: quiénes ocupan puesto, con puntaje y justificación.
- **Puntaje desglosado**: para cada candidato evaluado, cuántos puntos aportó
  cada componente (skills obligatorios, deseables, experiencia, inglés,
  disponibilidad) y con qué datos salió cada uno.
- **Criterios relajados**: qué se movió, de qué valor a qué valor y en qué
  orden (RF-06), y qué criterios no se relajan nunca.
- **Supuestos**: lo que el agente dio por cierto sin inventar datos
  (umbral y pesos de la configuración, skills obligatorios inviolables,
  datos que el reclutador no supo, modalidad compatible, fecha del correo
  para fechas relativas).

El reporte se arma solo con el estado final del matching: no vuelve a puntuar
ni consulta al LLM, así que es reproducible (RNF-03).
"""

import csv
import json
from collections import Counter
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
REPORTS = RAIZ / "reports"

COMPONENTES = (
    ("mandatory_skills", "Skills obligatorios"),
    ("desirable_skills", "Skills deseables"),
    ("experience", "Experiencia"),
    ("english", "Inglés"),
    ("availability", "Disponibilidad"),
)


def _peso(pesos: dict, clave: str) -> float:
    return float(pesos.get(clave, 0) or 0)


def desglose_candidato(resultado: dict, pesos: dict, umbral: float) -> dict:
    """Puntaje de un candidato abierto componente por componente."""

    criterios = resultado.get("criterios") or {}
    detalle = resultado.get("detalle") or {}

    componentes = []
    for clave, etiqueta in COMPONENTES:
        valor = float(criterios.get(clave, 0) or 0)
        componentes.append(
            {
                "componente": clave,
                "etiqueta": etiqueta,
                "puntos": round(valor, 2),
                "maximo": _peso(pesos, clave),
                "valor": _explicar_componente(clave, detalle),
            }
        )

    return {
        "id": resultado.get("id", ""),
        # Absoluto para que se pueda comparar directamente con el umbral.
        "puntaje_absoluto": round(float(resultado.get("puntaje", 0) or 0), 2),
        "puntaje": resultado.get("puntaje", 0),
        "umbral": umbral,
        "supera_umbral": float(resultado.get("puntaje", 0) or 0) >= umbral,
        "cumple_requisitos": bool(resultado.get("cumple_requisitos")),
        "en_shortlist": bool(resultado.get("posicion")),
        "posicion": resultado.get("posicion"),
        "componentes": componentes,
        "justificacion": resultado.get("justificacion") or resultado.get("motivo", ""),
    }


def _explicar_componente(clave: str, detalle: dict) -> str:
    """Texto corto con los datos concretos que sostienen los puntos."""

    if clave == "mandatory_skills":
        cumplidos = detalle.get("cumplidos") or []
        faltantes = detalle.get("faltantes") or []
        total = len(detalle.get("obligatorios") or [])
        texto = f"{len(cumplidos)}/{total}"
        if cumplidos:
            texto += f" ({', '.join(cumplidos)})"
        if faltantes:
            texto += f"; faltan {', '.join(faltantes)}"
        return texto

    if clave == "desirable_skills":
        cumplidos = detalle.get("deseables_cumplidos") or []
        return ", ".join(cumplidos) if cumplidos else "ninguno"

    if clave == "experience":
        return (
            f"{detalle.get('experiencia', 0)} de "
            f"{detalle.get('experiencia_requerida', 0)} años"
        )

    if clave == "english":
        return (
            f"{detalle.get('nivel_candidato') or 'sin dato'} "
            f"(requiere {detalle.get('nivel_requerido') or 'sin dato'})"
        )

    fecha = detalle.get("fecha_candidato") or "sin fecha"
    requerida = detalle.get("fecha_requerida") or "sin fecha requerida"
    modalidad = detalle.get("modalidad_candidato") or "sin dato"
    estado = "a tiempo" if detalle.get("a_tiempo") else "no cumple fecha"
    if not detalle.get("modalidad_ok"):
        estado += ", modalidad no compatible"
    return f"disponible {fecha} para {requerida} ({estado}); modalidad {modalidad}"


def columnas_desglose(evaluados: list[dict]) -> dict:
    """Agrupa a los evaluados por el componente que más puntos les descontó.

    Sirve para ver de un vistazo qué criterio dejó fuera a más perfiles.
    """

    perdidas = Counter()
    puntos_perdidos = Counter()

    for evaluado in evaluados:
        for componente in evaluado["componentes"]:
            faltan = componente["maximo"] - componente["puntos"]
            if faltan > 0:
                perdidas[componente["etiqueta"]] += 1
                puntos_perdidos[componente["etiqueta"]] += faltan

    return {
        "candidatos_por_componente": dict(perdidas),
        "puntos_perdidos_por_componente": {
            nombre: round(valor, 2) for nombre, valor in puntos_perdidos.items()
        },
    }


def criterios_de_vacante(vacante: dict) -> dict:
    """Criterios con los que se evaluó la vacante (ya con relajaciones)."""

    return {
        "skills_obligatorios": list(vacante.get("skills_obligatorios") or []),
        "skills_deseables": list(vacante.get("skills_deseables") or []),
        "experience_required": vacante.get("experience_required"),
        "english_required": vacante.get("english_required"),
        "availability_required": vacante.get("availability_required"),
        "modality": vacante.get("modality"),
    }


def _consultas_no_respondidas(consultas: list[dict]) -> list[dict]:
    """Consultas al reclutador que quedaron sin dato (no se inventó nada)."""

    return [
        consulta
        for consulta in consultas
        if consulta.get("resultado") in {"no_se_sabe", "sin_respuesta", "limite_alcanzado"}
    ]


def supuestos(reporte: dict, config, parametros: dict | None = None) -> list[dict]:
    """Supuestos con los que se generó el reporte (RF-11).

    Cada supuesto dice qué se asumió y de dónde sale, para que el reclutador
    pueda cuestionarlo. No son datos inventados: son las reglas con las que
    el agente trabajó.
    """

    tabla = []

    def agregar(tema: str, supuesto: str, fuente: str) -> None:
        tabla.append({"tema": tema, "supuesto": supuesto, "fuente": fuente})

    agregar(
        "Umbral de puntaje",
        f"Un perfil entra a la shortlist con {config.threshold:g} puntos o más y "
        "cumpliendo todos los requisitos duros.",
        f"data/config.yaml -> scoring.threshold (umbral {config.threshold:g})",
    )
    pesos = ", ".join(
        f"{etiqueta.lower()} {_peso(config.pesos, clave):g}"
        for clave, etiqueta in COMPONENTES
    )
    agregar(
        "Pesos del puntaje",
        f"El puntaje reparte 100 puntos así: {pesos}.",
        "data/config.yaml -> scoring.weights",
    )
    agregar(
        "Skills obligatorios",
        "Los skills obligatorios no se relajan nunca; un perfil que no los tiene "
        "todos no entra, aunque el puesto quede libre.",
        "src/relajacion.py",
    )
    agregar(
        "Orden de relajación",
        "Las relajaciones se aplican en orden: fecha de inicio (+2 semanas), "
        f"experiencia (-1 año) e inglés (-1 nivel), hasta "
        f"{config.max_relajaciones} en total.",
        "data/config.yaml -> relaxation",
    )
    agregar(
        "Compatibilidad de modalidad",
        "Un candidato remoto sirve para cualquier modalidad y uno híbrido cubre "
        "una vacante presencial; la modalidad no se relaja.",
        "src/scoring.py -> _modalidad_compatible",
    )
    agregar(
        "Datos faltantes",
        "Si el reclutador no confirma un dato (\"no se sabe\" o se agotó el límite "
        f"de {config.max_consultas_reclutador} consultas), el campo queda vacío y "
        "se puntúa 0 en lugar de inventarlo.",
        "src/reclutador.py",
    )
    agregar(
        "Puntaje versus redacción",
        "El puntaje siempre lo calcula el código; con LLM solo cambia la "
        "redacción de la justificación.",
        f"AGENTE_MODO = {config.modo}",
    )

    if parametros:
        for clave, valor in parametros.items():
            agregar("Parámetro del origen", f"{clave}: {valor}", "bandeja simulada")
    return tabla


def observaciones(reporte: dict) -> list[str]:
    """Supuestos que dependen de los datos concretos de esta corrida."""

    notas = []
    consultas = reporte.get("consultas_reclutador") or []
    no_respondidas = _consultas_no_respondidas(consultas)
    if no_respondidas:
        ids = ", ".join(sorted({c.get("candidato_id", "") for c in no_respondidas}))
        notas.append(
            f"Datos sin confirmar: {len(no_respondidas)} consulta(s) al reclutador "
            f"quedaron sin respuesta ({ids}); esos perfiles se puntuaron sin la "
            "fecha de disponibilidad."
        )

    sin_fecha = [
        e["id"]
        for e in reporte["candidatos"]
        if not (e.get("detalle") or {}).get("fecha_candidato")
    ]
    if sin_fecha:
        notas.append(
            f"{len(sin_fecha)} perfil(es) sin fecha de disponibilidad: "
            f"{', '.join(sin_fecha[:10])}{'...' if len(sin_fecha) > 10 else ''}. "
            "No se asumió una fecha por ellos."
        )

    relajaciones = reporte.get("criterios_relajados") or []
    if relajaciones:
        notas.append(
            "La shortlist se armó con criterios relajados; sin esas relajaciones "
            "la cantidad de perfiles sería menor."
        )
    else:
        notas.append(
            "No se relajó ningún criterio: la shortlist se armó con los criterios "
            "originales de la vacante."
        )

    if reporte.get("duplicados"):
        notas.append(
            f"Se descartaron {len(reporte['duplicados'])} perfil(es) duplicado(s): "
            "cada persona se evaluó una sola vez."
        )

    # La fecha relajada también se usa en la justificación, así que se avisa
    # para que nadie lea "a tiempo" contra la fecha original. Coincide con
    # las relajaciones aplicadas en esta corrida.
    fecha_original = (reporte.get("criterios_originales") or {}).get(
        "availability_required"
    )
    fecha_vigente = (reporte.get("criterios_vigentes") or {}).get(
        "availability_required"
    )
    if fecha_original and fecha_vigente and fecha_original != fecha_vigente:
        notas.append(
            "La disponibilidad se comparó contra la fecha ya relajada "
            f"({fecha_vigente}); la vacante pedía {fecha_original}. Algunos "
            "perfiles aparecen \"a tiempo\" solo por esa relajación."
        )
    return notas


def construir_reporte(resultado: dict, config) -> dict:
    """Arma el reporte de una vacante a partir del estado final del matching."""

    vacante = resultado["vacante_actual"]
    original = resultado.get("vacante_original") or vacante
    analisis = resultado.get("analisis_shortlist") or {}
    evaluacion = resultado.get("evaluacion") or {}
    umbral = config.threshold

    evaluados = [
        {
            **desglose_candidato(item, config.pesos, umbral),
            "detalle": item.get("detalle") or {},
        }
        for item in resultado.get("calificados") or []
    ]

    pocicionados = sorted(
        (item for item in evaluados if item["en_shortlist"]),
        key=lambda item: item["posicion"] or 0,
    )

    por_id = {item["id"]: item for item in evaluados}
    relajaciones = [
        {
            "orden": relajacion.get("iteracion", indice),
            "tipo": relajacion.get("tipo", ""),
            "antes": relajacion.get("antes"),
            "despues": relajacion.get("despues"),
            "descripcion": relajacion.get("descripcion", ""),
        }
        for indice, relajacion in enumerate(
            resultado.get("relajaciones_aplicadas") or [], start=1
        )
    ]

    reporte = {
        "vacante": {
            "id": vacante.get("id", ""),
            "titulo": vacante.get("titulo", ""),
            "escenario": vacante.get("scenario", ""),
            "estado": resultado.get("estado", ""),
            "modo": config.modo,
        },
        "vacante_original": original,
        "criterios_vigentes": criterios_de_vacante(vacante),
        "criterios_originales": criterios_de_vacante(original),
        "configuracion": {
            "umbral": umbral,
            "pesos": dict(config.pesos),
            "shortlist_size": config.shortlist_size,
            "max_relajaciones": config.max_relajaciones,
        },
        "resultado": {
            "exito": bool(evaluacion.get("exito")),
            "aptos": evaluacion.get("aptos", 0),
            "minimo": evaluacion.get("minimo", 0),
            "puestos_llenos": len(resultado.get("shortlist") or []),
            "puestos_libres": analisis.get(
                "puestos_libres", evaluacion.get("puestos_libres", 0)
            ),
            "requiere_revision_humana": bool(resultado.get("requiere_revision_humana")),
            "requisito_bloqueante": analisis.get("requisito_principal", ""),
            "motivo_incompleta": analisis.get("motivo_principal", ""),
            "bloqueantes": analisis.get("bloqueantes", []),
        },
        "shortlist": [
            {
                "posicion": por_id[identificador]["posicion"],
                "id": identificador,
                "puntaje": por_id[identificador]["puntaje"],
                "justificacion": por_id[identificador]["justificacion"],
                "desglose": por_id[identificador]["componentes"],
            }
            for identificador in (item["id"] for item in pocicionados)
        ],
        "candidatos": [
            {**evaluado, "detalle": por_id[evaluado["id"]]["detalle"]}
            for evaluado in evaluados
        ],
        "criterios_relajados": relajaciones,
        "consultas_reclutador": resultado.get("consultas_reclutador") or [],
        "duplicados": resultado.get("duplicados") or [],
        "limites": resultado.get("limites") or config.limites(),
        "pasos_grafo": resultado.get("pasos_grafo", 0),
    }
    reporte.update(columnas_desglose(evaluados))
    reporte["supuestos"] = supuestos(reporte, config)
    reporte["observaciones"] = observaciones(reporte)
    return reporte


def _tabla(filas: list[list], encabezado: list[str]) -> list[str]:
    lineas = ["| " + " | ".join(encabezado) + " |"]
    lineas.append("|" + "|".join("---" for _ in encabezado) + "|")
    for fila in filas:
        lineas.append("| " + " | ".join(str(valor) for valor in fila) + " |")
    return lineas


def renderizar_markdown(reporte: dict) -> str:
    """Convierte el reporte en un Markdown legible."""

    vacante = reporte["vacante"]
    resultado = reporte["resultado"]
    lineas = [
        f"# Reporte de la vacante {vacante['id']}: {vacante['titulo']}",
        "",
        f"- **Escenario:** {vacante['escenario'] or 'sin escenario'}",
        f"- **Estado:** {vacante['estado']} "
        f"({'éxito' if resultado['exito'] else 'sin éxito pleno'})",
        f"- **Modo:** {vacante['modo']}",
        f"- **Puestos:** {resultado['puestos_llenos']} cubiertos, "
        f"{resultado['puestos_libres']} libres",
        f"- **Revisión humana:** {'sí' if resultado['requiere_revision_humana'] else 'no'}",
        "",
    ]

    if resultado["puestos_libres"]:
        lineas += [
            "## Shortlist parcial (RF-07)",
            "",
            f"Requisito bloqueante: **{resultado['requisito_bloqueante'] or 'no identificado'}**.",
            "",
            resultado["motivo_incompleta"] or "",
            "",
        ]
        for bloque in resultado["bloqueantes"]:
            lineas.append(f"- **{bloque['requisito']}**: {'; '.join(bloque['casos'])}")
        lineas.append("")

    lineas += ["## Shortlist", ""]
    if not reporte["shortlist"]:
        lineas += ["_Ningún candidato ocupa puesto._", ""]
    else:
        for item in reporte["shortlist"]:
            lineas += [
                f"### {item['posicion']}. {item['id']} - {item['puntaje']:g} puntos",
                "",
                item["justificacion"],
                "",
                "| Componente | Puntos | Máximo | Datos |",
                "|---|---|---|---|",
            ]
            for componente in item["desglose"]:
                lineas.append(
                    f"| {componente['etiqueta']} | {componente['puntos']:g} | "
                    f"{componente['maximo']:g} | {componente['valor']} |"
                )
            lineas.append("")

    lineas += [
        "## Puntaje desglosado de todos los candidatos",
        "",
        "Ordenado de mayor a menor puntaje. La columna *Puesto* dice si entró "
        "a la shortlist.",
        "",
    ]
    filas = []
    for candidato in reporte["candidatos"]:
        puntos = {
            componente["etiqueta"]: componente["puntos"]
            for componente in candidato["componentes"]
        }
        filas.append(
            [
                candidato["id"],
                f"{candidato['puntaje']:g}",
                *[f"{puntos[etiqueta]:g}" for _, etiqueta in COMPONENTES],
                "sí" if candidato["en_shortlist"] else "no",
                "sí" if candidato["cumple_requisitos"] else "no",
                candidato["posicion"] or "",
            ]
        )
    lineas += _tabla(
        filas,
        [
            "Candidato",
            "Total",
            *[etiqueta for _, etiqueta in COMPONENTES],
            "En shortlist",
            "Cumple requisitos",
            "Puesto",
        ],
    )
    lineas += [
        "",
        "### Qué criterio dejó fuera a más perfiles",
        "",
    ]
    perdidas = sorted(
        reporte["puntos_perdidos_por_componente"].items(),
        key=lambda item: -item[1],
    )
    if not perdidas:
        lineas += ["_Todos los perfiles suman el puntaje completo._", ""]
    else:
        filas = [
            [
                etiqueta,
                reporte["candidatos_por_componente"].get(etiqueta, 0),
                f"{puntos:g}",
            ]
            for etiqueta, puntos in perdidas
        ]
        lineas += _tabla(filas, ["Componente", "Candidatos con pérdida", "Puntos perdidos"])
        lineas.append("")

    lineas += ["## Criterios relajados (RF-06)", ""]
    if reporte["criterios_relajados"]:
        filas = [
            [
                relajacion["orden"],
                relajacion["tipo"],
                relajacion["antes"],
                relajacion["despues"],
                relajacion["descripcion"],
            ]
            for relajacion in reporte["criterios_relajados"]
        ]
        lineas += _tabla(filas, ["#", "Criterio", "Antes", "Después", "Descripción"])
    else:
        lineas += ["_No se relajó ningún criterio._"]
    lineas += [
        "",
        f"Los skills obligatorios **no se relajan**. Se aplicaron "
        f"{len(reporte['criterios_relajados'])} de "
        f"{reporte['configuracion']['max_relajaciones']} relajaciones permitidas.",
        "",
        "### Criterios originales y vigentes",
        "",
    ]
    filas = [
        [
            campo,
            reporte["criterios_originales"].get(campo),
            reporte["criterios_vigentes"].get(campo),
        ]
        for campo in (
            "skills_obligatorios",
            "skills_deseables",
            "experience_required",
            "english_required",
            "availability_required",
            "modality",
        )
    ]
    lineas += _tabla(filas, ["Criterio", "Original", "Vigente"])
    lineas.append("")

    lineas += ["## Supuestos", ""]
    lineas += _tabla(
        [[s["tema"], s["supuesto"], s["fuente"]] for s in reporte["supuestos"]],
        ["Tema", "Supuesto", "Fuente"],
    )
    lineas += ["", "### Notas de esta corrida", ""]
    lineas += [f"- {nota}" for nota in reporte["observaciones"]]
    lineas += [
        "",
        "## Consultas al reclutador (RF-04)",
        "",
    ]
    if reporte["consultas_reclutador"]:
        lineas += _tabla(
            [
                [c.get("candidato_id", ""), c.get("campo", ""), c.get("respuesta", ""),
                 c.get("resultado", ""), c.get("motivo", "")]
                for c in reporte["consultas_reclutador"]
            ],
            ["Candidato", "Campo", "Respuesta", "Resultado", "Motivo"],
        )
    else:
        lineas.append("_No se hicieron consultas._")
    lineas += [
        "",
        "## Límites de la corrida (RNF-04)",
        "",
        f"- Pasos del grafo usados: {reporte['pasos_grafo']}",
    ]
    for clave, valor in (reporte.get("limites") or {}).items():
        lineas.append(f"- {clave}: {valor}")
    lineas.append("")
    return "\n".join(lineas)





def exportar_desglose_csv(reporte: dict, ruta: Path) -> None:
    """CSV plano del puntaje desglosado, para abrirlo en Excel."""

    ruta.parent.mkdir(parents=True, exist_ok=True)
    campos = [
        "id",
        "puntaje",
        "umbral",
        "supera_umbral",
        "cumple_requisitos",
        "en_shortlist",
        "posicion",
        *[clave for clave, _ in COMPONENTES],
    ]
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=campos)
        escritor.writeheader()
        for candidato in reporte["candidatos"]:
            fila = {
                campo: candidato.get(campo, "")
                for campo in campos
                if campo in candidato
            }
            for componente in candidato["componentes"]:
                fila[componente["componente"]] = componente["puntos"]
            escritor.writerow(fila)


def generar_reporte(resultado: dict, config, directorio: Path | None = None) -> dict:
    """Genera el reporte de una vacante y deja Markdown, JSON y CSV.

    Devuelve las rutas creadas y el reporte en memoria.
    """

    directorio = Path(directorio) if directorio else REPORTS
    reporte = construir_reporte(resultado, config)
    vacante_id = reporte["vacante"]["id"] or "sin_id"

    rutas = {
        "markdown": directorio / f"reporte_{vacante_id}.md",
        "json": directorio / f"reporte_{vacante_id}.json",
        "csv": directorio / f"puntajes_{vacante_id}.csv",
    }
    directorio.mkdir(parents=True, exist_ok=True)

    rutas["markdown"].write_text(renderizar_markdown(reporte), encoding="utf-8")
    with rutas["json"].open("w", encoding="utf-8") as archivo:
        json.dump(reporte, archivo, ensure_ascii=False, indent=2)
        archivo.write("\n")
    exportar_desglose_csv(reporte, rutas["csv"])

    return {"reporte": reporte, "rutas": rutas}


def main() -> int:
    """Corre el matching de una vacante y genera su reporte (RF-11)."""

    import argparse
    import sys

    from src.configuracion import cargar_configuracion
    from src.ejecutar_matching import ejecutar_vacante

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Genera el reporte por vacante con shortlist, puntajes y supuestos."
    )
    parser.add_argument("vacante", nargs="?", default="V001", help="ID de la vacante")
    argumentos = parser.parse_args()

    resultado = ejecutar_vacante(argumentos.vacante)
    generado = generar_reporte(resultado, cargar_configuracion())
    reporte = generado["reporte"]

    print(f"Reporte de {reporte['vacante']['id']} ({reporte['vacante']['titulo']})")
    print(f"Estado: {reporte['vacante']['estado']}")
    print(
        f"Shortlist: {reporte['resultado']['puestos_llenos']} puesto(s), "
        f"{reporte['resultado']['puestos_libres']} libre(s)"
    )
    print(f"Candidatos evaluados: {len(reporte['candidatos'])}")
    print(f"Relajaciones aplicadas: {len(reporte['criterios_relajados'])}")
    print(f"Supuestos registrados: {len(reporte['supuestos'])}")
    for nombre, ruta in generado["rutas"].items():
        print(f"   {nombre}: {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
