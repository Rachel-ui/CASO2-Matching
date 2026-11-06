#!/usr/bin/env python3
"""Demostración de RF-01, RF-16, RNF-08 y RF-08 con el LLM real.

Cuatro secciones, en este orden:

1. RF-16: clasificación de correos con el LLM (vacante nueva, no relacionado,
   duplicado y un correo sin rol ni skills -> revisión humana).
2. RF-01: extracción de requisitos del correo, mostrando qué campo puso el LLM,
   qué completaron las reglas y qué quedó vacío (nada se inventa).
3. RNF-08: fallo del LLM (doble que siempre falla) -> reintento, error en la
   auditoría y justificación por plantilla. El puntaje no cambia.
4. RF-08: aprobación humana con `interrupt` de LangGraph: se rechaza un
   candidato, se busca reemplazo y se vuelve a pedir aprobación.

Uso:

    python demo_requisitos.py                # todo (usa el LLM del .env)
    python demo_requisitos.py --sin-llm      # solo RF-08 y RNF-08, sin red
    python demo_requisitos.py V001 --rechazar C004   # otra vacante / otro rechazo

El caso 3 no llama a OpenRouter: usa un doble, así que no consume cuota.

Si el LLM no responde (sin clave, sin red o cuota diaria agotada), las
secciones 1 y 2 no se caen: muestran el error y siguen con el respaldo por
reglas (RNF-08). La sección 4 usa V003 por defecto porque es la vacante donde
el rechazo tiene reemplazo (C014 entra por C013).
"""

import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def titulo(texto: str) -> None:
    print("\n" + "=" * 70)
    print(texto)
    print("=" * 70)


CORREOS = {
    "vacante nueva": {
        "message_id": "demo-1",
        "remitente": "rrhh@ejemplo.com",
        "asunto": "Vacante: Desarrollador Backend Python",
        "cuerpo": (
            "Hola, necesitamos cubrir un puesto de Desarrollador Backend Python "
            "para el equipo de plataforma. Se requiere Python, SQL, Git y REST API; "
            "deseables Docker, FastAPI y Django. Experiencia mínima de 3 años, "
            "inglés B1, modalidad remoto y disponible para iniciar el 25/10/2026."
        ),
    },
    "no relacionado": {
        "message_id": "demo-2",
        "remitente": "facturacion@proveedor.com",
        "asunto": "Factura 0042 - octubre",
        "cuerpo": (
            "Estimados, adjuntamos la factura 0042 por los servicios de octubre. "
            "El pago vence el 30/10/2026. Cualquier consulta a facturación."
        ),
    },
    "sin rol ni skills": {
        "message_id": "demo-3",
        "remitente": "gerencia@ejemplo.com",
        "asunto": "Necesitamos gente para el área",
        "cuerpo": (
            "Buenas, necesitamos contratar personal porque el equipo está corto. "
            "Por favor ayúdennos a conseguir candidatos cuanto antes."
        ),
    },
}


# ── 1 y 2: RF-16 + RF-01 ────────────────────────────────────────


def _campos(datos: dict) -> dict:
    return {
        "rol": datos.get("titulo") or datos.get("rol") or "",
        "skills_obligatorios": datos.get("skills_obligatorios") or [],
        "skills_deseables": datos.get("skills_deseables") or [],
        "experiencia": datos.get("experience_required"),
        "ingles": datos.get("english_required"),
        "modalidad": datos.get("modality"),
        "inicio": datos.get("availability_required"),
    }


def _es_duplicado(clasificado: dict) -> bool:
    """El LLM puede decir `duplicado`; las reglas solo ven rol y skills."""

    return str(clasificado.get("clase") or "").strip() == "duplicado"


def clasificacion_y_extraccion() -> None:
    from src.clasificar_correos import clasificar_con_llm, clasificar_por_reglas
    from src.llm_cliente import crear_llm, modelo_actual

    titulo(f"1. RF-16: CLASIFICACIÓN CON EL LLM (modelo {modelo_actual()})")

    llm = crear_llm()
    resultados = {}
    for etiqueta, correo in CORREOS.items():
        clasificado = clasificar_con_llm(correo, llm, vacantes_recibidas=[])
        resultados[etiqueta] = clasificado
        print(f"\n[Correo: {etiqueta}] asunto: {correo['asunto']}")
        print(f"  clase  : {clasificado.get('clase')}")
        print(f"  fuente : {clasificado.get('fuente')}")
        print(f"  motivo : {clasificado.get('motivo')}")
        advertencias = clasificado.get("advertencias") or []
        if advertencias:
            print(f"  avisos : {advertencias}")
        if clasificado.get("fuente") != "llm":
            # El error completo (429, 404, JSON inválido...) queda en los avisos.
            print("  (el LLM no respondió; se usó el respaldo de la fase 1)")

    # Duplicado: el LLM recibe la lista de vacantes ya recibidas.
    print("\n[Correo: reenvío de la misma vacante]")
    recibidas = [] if _es_duplicado(resultados["vacante nueva"]) else [
        resultados["vacante nueva"].get("vacante") or {}
    ]
    if not recibidas:
        print(
            "  (la primera clasificación usó las reglas y no guarda vacante; se "
            "usa la vacante por reglas como 'ya recibida')"
        )
        recibidas = [clasificar_por_reglas(CORREOS["vacante nueva"]).get("vacante") or {}]
    duplicado = clasificar_con_llm(CORREOS["vacante nueva"], llm, vacantes_recibidas=recibidas)
    print(f"  clase  : {duplicado.get('clase')}")
    print(f"  fuente : {duplicado.get('fuente')}")
    print(f"  motivo : {duplicado.get('motivo')}")
    if duplicado.get("fuente") != "llm":
        # Las reglas no ven la lista de recibidas: el duplicado lo decide `encolar`.
        print(
            "  (con el LLM, este caso devuelve 'duplicado'; con el respaldo por "
            "reglas lo resuelve `encolar` en código)"
        )

    titulo("2. RF-01: EXTRACCIÓN DE REQUISITOS (LLM + reglas)")
    correo = CORREOS["vacante nueva"]
    clasificado = resultados["vacante nueva"]
    datos = clasificado.get("vacante") or {}
    print(f"Fuente de la clasificación: {clasificado.get('fuente')}\n")

    if clasificado.get("fuente") == "llm":
        print("Lo que devolvió el LLM (validado y normalizado):")
        for campo, valor in _campos(datos).items():
            print(f"  {campo:<20}: {valor}")
    else:
        print(
            "El LLM no respondió: los requisitos salen de las reglas del texto "
            "(RNF-08). Con el LLM disponible, esta tabla muestra lo que devuelve "
            "él y las reglas solo completan los huecos."
        )

    reglas = _campos(clasificar_por_reglas(correo).get("vacante") or {})
    if clasificado.get("fuente") == "llm":
        print("\nLo que aportan las reglas (solo para los huecos del LLM):")
        for campo, valor in reglas.items():
            print(f"  {campo:<20}: {valor}")

    completados = [
        campo
        for campo, valor in _campos(datos).items()
        if valor in ("", [], None) and reglas.get(campo) not in ("", [], None)
    ]
    print(f"\nCampos que completaron las reglas: {completados or 'ninguno'}")
    print(
        "  (lo que el LLM devolvió no se reemplaza; lo que no está escrito no "
        "se inventa)"
    )


# ── 3: RNF-08 ───────────────────────────────────────────────────


class LLMQueFalla:
    """Doble del chat model: siempre falla, para ver el reintento (RNF-08)."""

    def __init__(self):
        self.llamadas = 0

    def invoke(self, *args, **kwargs):
        self.llamadas += 1
        raise ConnectionError(f"simulado: el proveedor no responde (intento {self.llamadas})")


def _evaluacion_de_prueba() -> dict:
    from src.configuracion import cargar_configuracion
    from src.ejecutar_matching import cargar_candidatos, cargar_vacante
    from src.scoring import evaluar_candidato

    vacante = cargar_vacante("V001")
    candidato = cargar_candidatos()[0]
    return candidato, vacante, evaluar_candidato(candidato, vacante, cargar_configuracion())


def reintento_y_respaldo() -> None:
    from src.llm_cliente import generar_justificacion_con_fallback

    titulo("3. RNF-08: REINTENTO Y REGLA DE RESPALDO SI EL LLM FALLA")

    candidato, vacante, evaluacion = _evaluacion_de_prueba()
    doble = LLMQueFalla()

    texto, fuente, error = generar_justificacion_con_fallback(doble, candidato, vacante, evaluacion)

    print(f"Intentos de llamada al LLM : {doble.llamadas} (1 + 1 reintento)")
    print(f"Fuente de la justificación : {fuente}")
    print(f"Error registrado (auditoría): {error[:150]}")
    print(f"Justificación por plantilla : {texto[:150]}")
    print(f"Puntaje (siempre en código): {evaluacion['puntaje']:g}")
    assert doble.llamadas == 2 and fuente == "plantilla" and texto == evaluacion["motivo"]
    print("\nOK: falló dos veces, no se detuvo la secuencia y el puntaje no cambió.")


# ── 4: RF-08 ────────────────────────────────────────────────────


def aprobacion_humana(vacante_id: str, rechazo: str | None) -> None:
    from src.aprobacion import aprobar_shortlist, resumen_aprobacion
    from src.configuracion import cargar_configuracion

    titulo(f"4. RF-08: APROBACIÓN HUMANA CON interrupt (vacante {vacante_id})")
    print(
        "Con interrupt: el grafo se pausa, devuelve la shortlist y espera un "
        "Command(resume=[...]). En la corrida automática no se detiene."
    )
    print(
        f"Umbral del puntaje: {cargar_configuracion().threshold:g}; un reemplazo "
        "tiene que superar ese umbral (los que no, no pueden ocupar puesto)."
    )

    if rechazo:
        print(f"Respuesta humana programada: rechazar {rechazo} (y aprobar el resto).")

    resultado = aprobar_shortlist(
        vacante_id,
        rechazos=[[rechazo]] if rechazo else [],
        interactivo=False,
    )

    print()
    for linea in resumen_aprobacion(resultado):
        print(linea)

    reemplazos = [i for i in resultado["shortlist"] if i.get("reemplaza_a")]
    for item in reemplazos:
        print(f"  Reemplazo: {item['id']} entra por {item['reemplaza_a']}")

    decisiones = [
        f"{paso.get('decision')}"
        for paso in resultado.get("auditoria", [])
        if paso.get("nodo") == "aprobacion_humana"
    ]
    print(f"\nAuditoría de la aprobación: {' -> '.join(decisiones)}")

    # RF-08: la búsqueda de reemplazo es parte del nodo; se muestra qué perfiles
    # podían reemplazar al rechazado y por qué no entraron.
    rechazados = resultado.get("aprobacion", {}).get("rechazados") or []
    if rechazados:
        config = cargar_configuracion()
        aptos = {
            item["id"]: item["puntaje"]
            for item in resultado.get("calificados", [])
            if item.get("cumple_requisitos") and item["puntaje"] >= config.threshold
        }
        libres = {k: v for k, v in aptos.items() if k not in rechazados}
        print(f"Perfiles aptos disponibles para reemplazo: {libres or 'ninguno'}")
        print(
            "  (los que reemplazaron ya están en la shortlist final; si no hay "
            "nuevos, el nodo lo registra como sin_reemplazo)"
        )
        if not any(item.get("reemplaza_a") for item in resultado["shortlist"]):
            print(
                f"  En {vacante_id} no hay otro perfil apto sobre el umbral: el "
                "rechazo deja el puesto sin cubrir y queda para revisión humana."
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo de RF-01, RF-16, RNF-08 y RF-08.")
    # V003 es la vacante donde el rechazo tiene reemplazo (C014 entra por C013).
    parser.add_argument("vacante", nargs="?", default="V003", help="ID de la vacante para RF-08")
    parser.add_argument("--rechazar", default="C013", help="ID a rechazar en RF-08 ('' = aprobar todo)")
    parser.add_argument("--sin-llm", action="store_true", help="Omite las secciones 1 y 2 (sin red)")
    argumentos = parser.parse_args()

    os.environ.setdefault("AGENTE_MODO", "with_llm")

    if argumentos.sin_llm:
        print("(modo sin LLM: se omiten RF-16 y RF-01)")
    else:
        try:
            clasificacion_y_extraccion()
        except Exception as error:  # sin clave, sin red o cuota agotada
            print(
                f"\n[RF-16/RF-01] El LLM no está disponible: "
                f"{type(error).__name__}: {error}"
            )
            print(
                "  La clasificación y la extracción siguen funcionando con las "
                "reglas (RNF-08); para verlas con el LLM, revisa la clave o la "
                "cuota y vuelve a correr la demo."
            )

    reintento_y_respaldo()
    aprobacion_humana(argumentos.vacante, argumentos.rechazar or None)
    print("\nDemo completa: RF-16, RF-01, RNF-08 y RF-08.")


if __name__ == "__main__":
    main()
