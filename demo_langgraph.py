#!/usr/bin/env python3
"""Demo visual: LangGraph + LLM de punta a punta (RF-01, RF-16, RNF-08, RF-08).

Muestra tres cosas:

1. La estructura del grafo (nodos y aristas) y su diagrama Mermaid.
2. El matching de una vacante **nodo por nodo**, en vivo (`stream`), con el
   estado que deja cada nodo y las llamadas reales al LLM.
3. La clasificación de un correo con el LLM (RF-16) y la extracción de los
   requisitos (RF-01) sobre la vacante resultante.

Uso:

    python demo_langgraph.py              # vacante V001 y una vacante de prueba
    python demo_langgraph.py V003         # otra vacante
    python demo_langgraph.py V001 --sin-llm

Las llamadas al LLM consumen cuota real de OpenRouter (la clave sale de .env).
"""

import argparse
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.configuracion import MODO_CON_LLM, cargar_configuracion
from src.estado_agente import crear_estado_inicial
from src.grafo_matching import app_matching, construir_grafo

CORREO_DEMO = {
    "message_id": "demo-0001",
    "remitente": "rrhh@ejemplo.com",
    "asunto": "Vacante: Desarrollador Backend Python",
    "cuerpo": (
        "Hola, necesitamos cubrir un puesto de Desarrollador Backend Python "
        "para el equipo de plataforma. Se requiere Python, SQL, Git y REST API; "
        "deseables Docker, FastAPI y Django. Experiencia mínima de 3 años, "
        "inglés B1, modalidad remoto y disponible para iniciar el 25/10/2026."
    ),
}


def titulo(texto: str) -> None:
    print("\n" + "=" * 64)
    print(texto)
    print("=" * 64)


# ── 1. Estructura del grafo ─────────────────────────────────────

def mostrar_estructura() -> None:
    titulo("1. ESTRUCTURA DEL GRAFO (LangGraph)")
    grafo = construir_grafo()
    dibujo = grafo.get_graph()

    print("Nodos:")
    for nombre in dibujo.nodes:
        if nombre not in ("__start__", "__end__"):
            print(f"  • {nombre}")

    print("\nAristas:")
    for arista in dibujo.edges:
        etiqueta = f"  [{arista.conditional}]" if arista.conditional else ""
        print(f"  {arista.source:>18} -> {arista.target:<18}{etiqueta}")

    print("\nDiagrama Mermaid (pegar en mermaid.live):")
    print(dibujo.draw_mermaid())


# ── 2. Matching nodo por nodo, en vivo ──────────────────────────

def resumir_nodo(nodo: str, salida: dict) -> str:
    """Una línea con lo relevante que devolvió el nodo."""

    if nodo == "validar_estado":
        return f"estado={salida.get('estado')}"
    if nodo == "depurar_duplicados":
        return (
            f"{len(salida.get('candidatos_filtrados', []))} candidatos únicos, "
            f"{len(salida.get('duplicados', []))} duplicado(s) descartados"
        )
    if nodo == "consultar_reclutador":
        consultas = salida.get("consultas_reclutador", [])
        return f"{len(consultas)} consulta(s) al reclutador"
    if nodo == "procesar_candidato":
        ultimo = (salida.get("resultados") or [{}])[-1]
        if not ultimo:
            return "sin candidato evaluado"
        return (
            f"{ultimo.get('id', '?')}: {ultimo.get('puntaje', 0):.1f} pts, "
            f"cumple={ultimo.get('cumple_requisitos')}, "
            f"justificación={ultimo.get('modo_justificacion')}"
        )
    if nodo == "decidir_siguiente_paso":
        return f"decisión={salida.get('decision_actual')}"
    if nodo == "generar_shortlist":
        ids = [item["id"] for item in salida.get("shortlist", [])]
        return f"shortlist: {', '.join(ids) or '(vacía)'}"
    if nodo == "evaluar_resultado":
        evaluacion = salida.get("evaluacion") or {}
        return (
            f"decisión={salida.get('decision_actual')}, "
            f"aptos={evaluacion.get('aptos')}, cubiertos={evaluacion.get('cubiertos')}"
        )
    if nodo == "relajar_criterios":
        cambios = salida.get("relajaciones_aplicadas", [])
        return f"{len(cambios)} relajación(es) aplicadas"
    if nodo == "aprobacion_humana":
        aprobacion = salida.get("aprobacion") or {}
        return f"aprobación={aprobacion.get('estado', 'sin dato')}"
    if nodo == "finalizar":
        return f"estado final={salida.get('estado')}"
    return ", ".join(sorted(salida)) or "(sin cambios)"


def ejecutar_en_vivo(vacante_id: str, modo: str) -> dict:
    titulo(f"2. MATCHING EN VIVO - vacante {vacante_id} (modo {modo})")

    from src.ejecutar_matching import cargar_candidatos, cargar_vacante

    estado = crear_estado_inicial(cargar_vacante(vacante_id), cargar_candidatos())
    config = cargar_configuracion()

    print(f"{'paso':>4}  {'nodo':<20} detalle")
    print("-" * 100)
    inicio = time.perf_counter()
    final = None
    paso = 0

    for actualizacion in app_matching.stream(
        estado,
        {
            "recursion_limit": config.recursion_limit,
            "configurable": {"thread_id": f"demo-{vacante_id}-{time.time_ns()}"},
        },
        stream_mode="updates",
    ):
        # En modo `updates` cada trozo trae un solo nodo con lo que devolvió.
        for nodo, salida in actualizacion.items():
            paso += 1
            salida = salida or {}
            if nodo == "finalizar":
                final = {**estado, **salida}
            else:
                estado = {**estado, **salida}
            llamadas = " [LLM]" if salida.get("llm_calls") else ""
            print(f"{paso:>4}  {nodo:<22} {resumir_nodo(nodo, salida)}{llamadas}")

    duracion = time.perf_counter() - inicio
    resultado = final or estado

    print("-" * 100)
    print(
        f"Pasos del grafo: {paso} | Llamadas al LLM: {resultado.get('llm_calls', 0)} "
        f"| Tiempo: {duracion:.2f} s"
    )
    print(f"Estado final: {resultado.get('estado')}")
    print(f"Shortlist: {[(i['id'], round(i['puntaje'], 1)) for i in resultado['shortlist']]}")
    print(f"Justificación de ejemplo:\n  {resultado['shortlist'][0]['justificacion'] if resultado['shortlist'] else '-'}")
    if resultado.get("errores"):
        # Un mismo fallo se repite por cada perfil: se resume, no se vuelca.
        print(f"Errores del LLM (RNF-08): {len(resultado['errores'])} registro(s)")
        print(f"  primero: {resultado['errores'][0][:220]}")
    return resultado


# ── 3. Clasificación del correo con el LLM ──────────────────────

def clasificar_con_llm_real() -> None:
    titulo("3. CLASIFICACIÓN DEL CORREO CON EL LLM (RF-16 + RF-01)")

    from src.clasificar_correos import clasificar_con_llm, requisitos_estructurados
    from src.llm_cliente import crear_llm

    llm = crear_llm()
    print("Correo de entrada:")
    print(f"  Asunto: {CORREO_DEMO['asunto']}")
    print(f"  Cuerpo: {CORREO_DEMO['cuerpo']}\n")

    inicio = time.perf_counter()
    clasificado = clasificar_con_llm(CORREO_DEMO, llm, vacantes_recibidas=[])
    duracion = time.perf_counter() - inicio

    print(f"Clase: {clasificado.get('clase')}")
    print(f"Fuente: {clasificado.get('fuente')}")
    print(f"Motivo: {clasificado.get('motivo')}")
    print(f"Tiempo: {duracion:.2f} s")

    print("\nRequisitos extraídos (RF-01):")
    for clave, valor in requisitos_estructurados(clasificado).items():
        print(f"  {clave}: {valor}")

    advertencias = clasificado.get("advertencias") or []
    print(f"\nAdvertencias: {advertencias or '(ninguna)'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo de LangGraph + LLM.")
    parser.add_argument("vacante", nargs="?", default="V001", help="ID de la vacante")
    parser.add_argument(
        "--sin-llm", action="store_true", help="Corre el matching en modo without_llm"
    )
    argumentos = parser.parse_args()

    # Mismo patrón que `src.ejecutar_matching`: AGENTE_MODO decide el modo.
    modo =  "without_llm" if argumentos.sin_llm else "with_llm"
    os.environ["AGENTE_MODO"] = modo

    mostrar_estructura()
    ejecutar_en_vivo(argumentos.vacante, modo)

    if modo == MODO_CON_LLM:
        clasificar_con_llm_real()
    else:
        print("\n(modo without_llm: se omite la clasificación con el LLM)")


if __name__ == "__main__":
    main()
