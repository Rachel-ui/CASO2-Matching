
"""Cliente del LLM a través de OpenRouter (RNF-01, RNF-02, RNF-08, RNF-09).

OpenRouter expone una API compatible con la de OpenAI, así que se usa
`langchain_openai.ChatOpenAI` apuntando a `https://openrouter.ai/api/v1`.
El modelo se elige con `LLM_MODEL` (por defecto uno de Claude) y la clave
vive en `.env` como `OPENROUTER_API_KEY`; nunca se escribe en el código.

Solo se usa cuando el modo es `with_llm`. En modo sin LLM este módulo no se
importa, así que el agente corre completo sin red ni clave.

RNF-08: si el LLM falla o devuelve un formato inválido, se reintenta una vez
(`con_reintento`) y, si vuelve a fallar, se usa la regla de respaldo. El error
queda en `ultimo_error()` para que el nodo lo registre en el log de auditoría.
"""

import os
import re
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
RUTA_ENV = RAIZ / ".env"

URL_OPENROUTER = "https://openrouter.ai/api/v1"
VARIABLE_API_KEY = "OPENROUTER_API_KEY"
VARIABLE_MODELO = "LLM_MODEL"
# API compatible con OpenAI; sirve cualquier proveedor (OpenRouter, Groq,
# Together, Ollama local...) cambiando URL y clave en `.env` (RNF-01).
VARIABLE_URL = "LLM_BASE_URL"
VARIABLE_API_KEY_GENERICA = "LLM_API_KEY"
# Groq tiene plan gratuito amplio (sin límite diario tan bajo como el de
# OpenRouter) y una API compatible con la de OpenAI.
URL_GROQ = "https://api.groq.com/openai/v1"
# OpenRouter cambió sus identificadores: los `anthropic/claude-3.5-*` ya no
# existen y la llamada devolvía 404 (la corrida caía siempre a la plantilla).
MODELO_POR_DEFECTO = "openai/gpt-4o-mini"
# Modelo que se usa cuando LLM_BASE_URL apunta a Groq (su plan gratis).
MODELO_POR_DEFECTO_GROQ = "llama-3.3-70b-versatile"

# RNF-08: un fallo y un reintento; después, la regla de respaldo.
MAX_INTENTOS_LLM = 2

# Último error del LLM, para registrarlo en el log (RNF-08/RF-10).
_ULTIMO_ERROR: list[str] = []

PROMPT_SISTEMA = (
    "Eres un reclutador técnico. Redactas justificaciones breves en español "
    "a partir de datos ya calculados. No inventes datos: si un campo no está, "
    "dilo. Nunca uses nombre, género, edad ni nacionalidad como criterio."
)


class ErrorLLM(RuntimeError):
    """Falta la configuración del LLM o la llamada falló."""


def _variables_clave() -> tuple[str, ...]:
    """Nombres aceptados: el genérico (`LLM_API_KEY`) y el de OpenRouter."""

    return (VARIABLE_API_KEY_GENERICA, VARIABLE_API_KEY)


def api_key_configurada(ruta: Path | None = None) -> bool:
    """Indica si hay clave del LLM en el entorno o en `.env` (RNF-09)."""

    return bool(_leer_api_key(ruta))


def _leer_api_key(ruta: Path | None = None) -> str:
    """Clave del LLM: primero el entorno, si no, la del `.env` (RNF-09)."""

    for nombre in _variables_clave():
        if os.getenv(nombre):
            return os.getenv(nombre)

    ruta = Path(ruta) if ruta else RUTA_ENV
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
            nombre, _, valor = linea.partition("=")
            if nombre.strip() in _variables_clave() and valor.strip():
                return valor.strip()

    return ""


def url_llm() -> str:
    """Endpoint compatible con OpenAI que usa el cliente."""

    return (os.getenv(VARIABLE_URL) or URL_OPENROUTER).rstrip("/")


def modelo_actual() -> str:
    if os.getenv(VARIABLE_MODELO):
        return os.getenv(VARIABLE_MODELO)
    if url_llm() == URL_GROQ.rstrip("/"):
        return MODELO_POR_DEFECTO_GROQ
    return MODELO_POR_DEFECTO


def crear_llm(max_llamadas: int = 30):
    """Crea el chat model de OpenRouter con timeout y reintentos acotados."""
    # Carga `.env` sin pisar las variables del entorno (RNF-09) y sin
    # inyectarlas en `os.environ`: la clave se busca con `api_key_configurada`.
    from dotenv import load_dotenv
    load_dotenv(RUTA_ENV, override=False)
    
    if not api_key_configurada():
        raise ErrorLLM(
            f"Falta {VARIABLE_API_KEY}. Agrégalo al archivo .env (RNF-09) "
            "o usa AGENTE_MODO=without_llm."
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=modelo_actual(),
        api_key=_leer_api_key(),
        base_url=url_llm(),
        temperature=0,
        timeout=30,
        max_retries=2,
        default_headers={"HTTP-Referer": "https://github.com/", "X-Title": "CASO2-Matching"},
        # El JSON de una vacante completa no cabe en 400 tokens (antes se
        # cortaba a medias y la clasificación caía siempre a las reglas).
        max_tokens=1200,
    )


def generar_justificacion(
    llm,
    candidato: dict,
    vacante: dict,
    evaluacion: dict,
) -> str:
    """Pide al LLM una justificación; el reintento y el respaldo son del llamador.

    El nodo del grafo usa `generar_justificacion_con_fallback` (RNF-08).
    """

    detalle = evaluacion["detalle"]
    contexto = (
        f"Vacante: {vacante.get('titulo', '')}\n"
        f"Puntaje calculado (no lo cambies): {evaluacion['puntaje']}/100\n"
        f"Skills obligatorios cumplidos: {', '.join(detalle['cumplidos']) or 'ninguno'}\n"
        f"Skills obligatorios faltantes: {', '.join(detalle['faltantes']) or 'ninguno'}\n"
        f"Deseables cumplidos: {', '.join(detalle['deseables_cumplidos']) or 'ninguno'}\n"
        f"Experiencia: {detalle['experiencia']} años (requiere {detalle['experiencia_requerida']})\n"
        f"Inglés: {detalle['nivel_candidato'] or 'sin dato'} "
        f"(requiere {detalle['nivel_requerido']})\n"
        f"Disponibilidad: {detalle['fecha_candidato'] or 'sin dato'} "
        f"(requiere para {detalle['fecha_requerida']})\n"
        f"Modalidad: {detalle['modalidad_candidato'] or 'sin dato'} "
        f"(vacante {detalle['modalidad_vacante']})\n"
        f"Cumple requisitos obligatorios: {'sí' if evaluacion['cumple_requisitos'] else 'no'}\n"
    )

    mensajes = [
        ("system", PROMPT_SISTEMA),
        (
            "user",
            "Redacta en 2 o 3 frases por qué este perfil entra o no entra "
            "en la shortlist, usando solo estos datos. No menciones el nombre del "
            "candidato ni datos personales.\n\n" + contexto,
        ),
    ]

    respuesta = llm.invoke(mensajes)
    texto = str(getattr(respuesta, "content", "") or "").strip()

    if not texto:
        raise ErrorLLM("El LLM devolvió una respuesta vacía.")

    return _limpiar_justificacion(texto)


def _limpiar_justificacion(texto: str) -> str:
    """Quita el razonamiento que algunos modelos gratis anteponen a la respuesta.

    Con `openrouter/free` el modelo puede devolver su cadena de pensamiento
    ("1. **Analyze the Request:** ...") antes de la justificación. Se corta
    desde el último encabezado de razonamiento y se deja solo el texto final.
    """

    marcas = (
        "**analyze the request",
        "**analyze the",
        "analyze the request",
        "**reasoning",
        "reasoning:",
        "**justificación",
        "justificación:",
    )
    lineas = texto.splitlines()
    inicio = 0
    for indice, linea in enumerate(lineas):
        if linea.strip().lower().startswith(marcas):
            inicio = indice + 1

    # Tras el razonamiento vienen viñetas y líneas en blanco: se saltan.
    while inicio < len(lineas) and (
        not lineas[inicio].strip()
        or lineas[inicio].strip()[0] in "*-•0123456789"
    ):
        inicio += 1

    limpio = "\n".join(lineas[inicio:]).strip()
    # Si el corte dejó solo viñetas o nada, se devuelve el texto original.
    if len(limpio) < 40:
        return texto
    return limpio


# ──────────────────────────────────────────────────────────────
# RNF-08: reintento y regla de respaldo si el LLM falla
# ──────────────────────────────────────────────────────────────


def _recordar_error(mensaje: str) -> None:
    """Deja el error para que el nodo lo registre en el log de auditoría."""

    _ULTIMO_ERROR.clear()
    _ULTIMO_ERROR.append(mensaje)


def ultimo_error() -> str:
    """Último error del LLM en el hilo actual ('' si no hubo).

    Un reintento que sí funcionó limpia el error: lo que queda es el fallo
    que obligó a usar la regla de respaldo.
    """

    return _ULTIMO_ERROR[0] if _ULTIMO_ERROR else ""


def resumir_error(error) -> str:
    """Motivo corto del fallo, para la consola y la auditoría (RNF-08).

    El error crudo de un proveedor puede traer el JSON completo de la
    respuesta (429 con la cuota, la lista de proveedores, el `user_id`...).
    Aquí se deja lo que sirve para actuar: el tipo, el código HTTP y el
    mensaje del proveedor, sin el resto del cuerpo.
    """

    texto = str(error)
    codigo = re.search(r"Error code: (\d{3})", texto)
    mensaje = re.search(r"'message': '([^']+)'", texto)
    if codigo or mensaje:
        partes = [type(error).__name__]
        if codigo:
            partes.append(f"HTTP {codigo.group(1)}")
        if mensaje:
            partes.append(mensaje.group(1))
        return " - ".join(partes)
    return f"{type(error).__name__}: {texto}"[:300]


def con_reintento(funcion, max_intentos: int = MAX_INTENTOS_LLM):
    """Ejecuta `funcion` y, si falla, la reintenta una vez más (RNF-08).

    Cualquier fallo (red, cuota, respuesta vacía o formato inválido, que se
    levanta como `ErrorLLM`) cuenta como intento. Si el último también falla,
    se relanza `ErrorLLM` con el motivo y queda en `ultimo_error()`.
    """

    ultimo = None
    for intento in range(1, max_intentos + 1):
        try:
            resultado = funcion()
        except Exception as error:  # red, cuota, formato o respuesta vacía
            ultimo = error
            continue
        _ULTIMO_ERROR.clear()
        return resultado

    mensaje = (
        f"el LLM falló en {max_intentos} intento(s): "
        f"{resumir_error(ultimo)}"
    )
    _recordar_error(mensaje)
    raise ErrorLLM(mensaje) from ultimo


def generar_justificacion_con_fallback(
    llm,
    candidato: dict,
    vacante: dict,
    evaluacion: dict,
) -> tuple[str, str, str]:
    """Justificación del LLM con reintento y respaldo (RNF-08).

    Devuelve `(texto, fuente, error)`: `fuente` es `llm` o `plantilla`. Si el
    LLM falla o devuelve un formato inválido dos veces, se usa la
    justificación por plantilla (la misma de `evaluacion`) y el error viaja en
    `error` para que el nodo lo registre en el log de auditoría.
    """

    try:
        texto = con_reintento(lambda: generar_justificacion(llm, candidato, vacante, evaluacion))
        return texto, "llm", ""
    except Exception as error:
        _recordar_error(str(error))
        return evaluacion["motivo"], "plantilla", ultimo_error()


PROMPT_CLASIFICACION = (
    "Clasifica un correo de una bandeja de reclutamiento y extrae los "
    "requisitos del puesto (RF-01/RF-16). Devuelve SOLO un objeto JSON con "
    "las claves: clase (\"vacante_nueva\", \"duplicado\" o \"no_relacionado\"), "
    "motivo (una frase), tipo_texto (vacante, candidato, boletin, factura o "
    "desconocido) y vacante. En vacante pon los campos titulo (SOLO el rol "
    "del puesto, por ejemplo \"Desarrollador Backend Python\"; nunca el saludo "
    "ni el cuerpo del correo), descripcion, skills_obligatorios (lista), "
    "skills_deseables (lista), experience_required (años, entero o null), english_required "
    "(A1..C2 o null), availability_required (fecha de inicio en YYYY-MM-DD o "
    "null) y modality (remoto, hibrido, presencial o null). Si el correo no "
    "pide contratar a nadie, usa \"no_relacionado\" y vacante null. Si reenvía "
    "una vacante que ya aparece en la lista de vacantes recibidas, usa "
    "\"duplicado\". No inventes skills, años, fechas ni niveles: si no están "
    "en el correo, usa null o lista vacía."
)


CLASES_VALIDAS = ("vacante_nueva", "duplicado", "no_relacionado")


def _formato_json() -> dict | None:
    """Guía de decodificación con salida JSON (si el proveedor la soporta)."""

    try:
        from langchain_core.utils.function_calling import convert_to_openai_response_format
    except ImportError:  # versión sin el helper: se pide el JSON en el prompt
        return None

    esquema = {
        "title": "ClasificacionCorreo",
        "type": "object",
        "properties": {
            "clase": {
                "type": "string",
                "enum": ["vacante_nueva", "duplicado", "no_relacionado"],
            },
            "motivo": {"type": "string"},
            "tipo_texto": {"type": ["string", "null"]},
            "vacante": {
                "type": ["object", "null"],
                "properties": {
                    "titulo": {"type": ["string", "null"]},
                    "descripcion": {"type": ["string", "null"]},
                    "skills_obligatorios": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "skills_deseables": {"type": "array", "items": {"type": "string"}},
                    "experience_required": {"type": ["integer", "null"]},
                    "english_required": {"type": ["string", "null"]},
                    "availability_required": {"type": ["string", "null"]},
                    "modality": {"type": ["string", "null"]},
                },
            },
        },
        "required": ["clase", "motivo"],
    }

    try:
        return convert_to_openai_response_format(("ClasificacionCorreo", esquema, None))
    except Exception:  # proveedor o versión sin structured output
        return None


def _contexto_vacantes_recibidas(vacantes_recibidas) -> str:
    """Resumen de las vacantes ya recibidas, para que el LLM reconozca reenvíos."""

    if not vacantes_recibidas:
        return "Vacantes ya recibidas: ninguna."

    lineas = ["Vacantes ya recibidas (rol, skills obligatorios, experiencia):"]
    for registro in vacantes_recibidas:
        datos = registro.get("vacante", registro) if isinstance(registro, dict) else {}
        lineas.append(
            f"- {datos.get('id', '')}: {datos.get('titulo', '')}; "
            f"skills: {', '.join(datos.get('skills_obligatorios') or []) or 'ninguno'}; "
            f"experiencia: {datos.get('experience_required') if datos.get('experience_required') is not None else 'sin dato'}"
        )
    return "\n".join(lineas)


def interpretar_correo_con_llm(llm, correo: dict, hoy=None, vacantes_recibidas=None) -> dict:
    """Fase 2 de RF-01/RF-16: el LLM clasifica el correo y extrae la vacante.

    `vacantes_recibidas` es la cola de vacantes ya aceptadas; se resumen en el
    prompt para que el LLM reconozca un reenvío (la decisión final de
    duplicado sigue en código).

    La respuesta se valida en `src.clasificar_correos` (rol y skills
    obligatorios siguen siendo obligatorios). Si el LLM devuelve algo que no
    es JSON, se levanta `ErrorLLM` y la clasificación cae a las reglas.
    """

    import json

    asunto = str(correo.get("asunto") or "")
    cuerpo = str(correo.get("cuerpo") or "")
    fecha = f"Fecha del correo: {hoy.isoformat()}\n" if hoy else ""
    recibidas = _contexto_vacantes_recibidas(vacantes_recibidas)

    mensajes = [
        ("system", PROMPT_SISTEMA + " " + PROMPT_CLASIFICACION),
        ("user", f"{fecha}{recibidas}\n\nAsunto: {asunto}\n\n{cuerpo}"),
    ]

    def _llamada() -> dict:
        try:
            formato = _formato_json()
            respuesta = llm.invoke(mensajes, **({"response_format": formato} if formato else {}))
        except TypeError:
            # El doble de las pruebas (o un modelo sin structured output) no
            # acepta `response_format`; se pide el JSON solo con el prompt.
            respuesta = llm.invoke(mensajes)
        texto = str(getattr(respuesta, "content", "") or "").strip()
        if not texto:
            raise ErrorLLM("El LLM devolvió una respuesta vacía.")

        inicio, fin = texto.find("{"), texto.rfind("}")
        if inicio == -1 or fin <= inicio:
            raise ErrorLLM("El LLM no devolvió un objeto JSON.")

        try:
            datos = json.loads(texto[inicio : fin + 1])
        except ValueError as error:
            raise ErrorLLM(f"El JSON del LLM no es válido: {error}") from error

        if not isinstance(datos, dict):
            raise ErrorLLM("El LLM no devolvió un objeto JSON.")

        if str(datos.get("clase") or "").strip() not in CLASES_VALIDAS:
            # Formato inválido: se reintenta y, si repite, mandan las reglas.
            raise ErrorLLM(
                f"El LLM devolvió una clase no válida ({datos.get('clase')!r})."
            )

        return {**datos, "llm_calls": 1}

    # RNF-08: se reintenta una vez antes de caer a las reglas.
    return con_reintento(_llamada)
