
"""Cliente del LLM a través de OpenRouter (RNF-01, RNF-02, RNF-09).

OpenRouter expone una API compatible con la de OpenAI, así que se usa
`langchain_openai.ChatOpenAI` apuntando a `https://openrouter.ai/api/v1`.
El modelo se elige con `LLM_MODEL` (por defecto uno de Claude) y la clave
vive en `.env` como `OPENROUTER_API_KEY`; nunca se escribe en el código.

Solo se usa cuando el modo es `with_llm`. En modo sin LLM este módulo no se
importa, así que el agente corre completo sin red ni clave.
"""

import os
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
RUTA_ENV = RAIZ / ".env"

URL_OPENROUTER = "https://openrouter.ai/api/v1"
VARIABLE_API_KEY = "OPENROUTER_API_KEY"
VARIABLE_MODELO = "LLM_MODEL"
MODELO_POR_DEFECTO = "anthropic/claude-3.5-haiku"

PROMPT_SISTEMA = (
    "Eres un reclutador técnico. Redactas justificaciones breves en español "
    "a partir de datos ya calculados. No inventes datos: si un campo no está, "
    "dilo. Nunca uses nombre, género, edad ni nacionalidad como criterio."
)


class ErrorLLM(RuntimeError):
    """Falta la configuración del LLM o la llamada falló."""


def api_key_configurada(ruta: Path | None = None) -> bool:
    """Indica si hay clave de OpenRouter en el entorno o en `.env` (RNF-09)."""

    if os.getenv(VARIABLE_API_KEY):
        return True

    ruta = Path(ruta) if ruta else RUTA_ENV
    if not ruta.exists():
        return False

    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        clave, _, valor = linea.partition("=")
        if clave.strip() == VARIABLE_API_KEY and valor.strip():
            return True

    return False


def modelo_actual() -> str:
    return os.getenv(VARIABLE_MODELO) or MODELO_POR_DEFECTO


def crear_llm(max_llamadas: int = 30):
    """Crea el chat model de OpenRouter con timeout y reintentos acotados."""

    if not api_key_configurada():
        raise ErrorLLM(
            f"Falta {VARIABLE_API_KEY}. Agrégalo al archivo .env (RNF-09) "
            "o usa AGENTE_MODO=without_llm."
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=modelo_actual(),
        api_key=os.getenv(VARIABLE_API_KEY),
        base_url=URL_OPENROUTER,
        temperature=0,
        timeout=30,
        max_retries=2,
        default_headers={"HTTP-Referer": "https://github.com/", "X-Title": "CASO2-Matching"},
        max_tokens=400,
    )


def generar_justificacion(
    llm,
    candidato: dict,
    vacante: dict,
    evaluacion: dict,
) -> str:
    """Pide al LLM una justificación; si falla, usa la plantilla."""

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

    return texto
