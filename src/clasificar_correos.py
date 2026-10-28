"""Clasificación de correos y cola de vacantes (RF-16).

Cada correo que llega a la bandeja se clasifica en una de tres clases:

- `vacante_nueva`: describe un puesto con rol y skills obligatorios; es la
  única clase que entra a la cola y dispara el matching.
- `duplicado`: repite una vacante ya recibida (mismo ID o misma huella de
  rol + skills + criterios), así que se registra pero no vuelve a la cola.
- `no_relacionado`: gestión, perfil de candidato, boletín, factura o texto
  sin señales de puesto; nunca dispara el matching.

Si el correo sí parece una vacante pero no trae rol (título) ni skills
obligatorios, no se inventan criterios: queda en `revision_humana`. La
variante de texto que no alcanza para el matching también va a revisión, no a
"no relacionado", porque el remitente sí quería contratar.

Fase 1 (por reglas, reproducibles, sin red), según `AGENTE_MODO` o el
argumento `modo`:

- `without_llm`: interpretación determinista del texto (`interpretar_texto`).
- `with_llm`: el LLM decide la clase y extrae los campos; la validación y la
  detección de duplicados siguen en código (el LLM no decide qué entra).

En ambos modos la salida tiene la misma forma, para que la cola y el matching
no cambien de contrato.
"""

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

from src.duplicados import normalizar_texto
from src.interpretar_texto import (
    TIPO_CANDIDATO,
    TIPO_VACANTE,
    interpretar,
    interpretar_vacante,
)


VACANTE_NUEVA = "vacante_nueva"
DUPLICADO = "duplicado"
NO_RELACIONADO = "no_relacionado"
REVISION_HUMANA = "revision_humana"

CLASES = (VACANTE_NUEVA, DUPLICADO, NO_RELACIONADO, REVISION_HUMANA)

# Origen de la decisión, para la auditoría del reporte (RF-10/RF-16).
FUENTE_REGLAS = "reglas"
FUENTE_LLM = "llm"

RAIZ = Path(__file__).resolve().parent.parent
ARCHIVO_COLA = RAIZ / "data" / "cola_vacantes.json"

# Campos que definen la coherencia de una vacante ya estructurada
# (`vacante_estructurada` de la bandeja simulada).
# Palabras que acompañan a "vacante" o "solicitud" pero no nombran un cargo.
_PALABRAS_DEL_TRAMITE = {
    "vacantes", "vacante", "proceso", "solicitud", "solicitudes", "puesto",
    "cargo", "plaza", "requisitos", "detalles",
}

CAMPOS_DE_VACANTE = (
    "skills_obligatorios",
    "experience_required",
    "english_required",
    "availability_required",
    "modality",
)


class ErrorClasificacion(ValueError):
    """El correo no se puede clasificar ni marcando la revisión humana."""


def rol_de_vacante(datos: dict) -> str:
    """Rol del puesto: el título sin la palabra 'vacante' ni cortesías."""

    titulo = str(datos.get("titulo") or "").strip()
    titulo = normalizar_texto(titulo)
    titulo = titulo.removeprefix("solicitud de vacante:").strip()
    titulo = titulo.removeprefix("solicitud de vacante").strip(" :-")
    titulo = titulo.removeprefix("vacante:").strip()
    titulo = titulo.removeprefix("vacante de").strip()
    return titulo.strip()


def tiene_rol_y_skills(datos: dict) -> bool:
    """El mínimo para iniciar el matching: un rol y skills obligatorios."""

    skills = [
        str(skill).strip()
        for skill in (datos.get("skills_obligatorios") or [])
        if str(skill).strip()
    ]
    return bool(rol_de_vacante(datos)) and bool(skills)


def huella_vacante(datos: dict) -> str:
    """Identidad del puesto: rol + skills obligatorios + criterios vigentes.

    Dos correos con la misma huella describen la misma solicitud aunque
    cambien de ID o el reclutador la reenvíe con otro asunto.
    """

    partes = [
        rol_de_vacante(datos),
        "|".join(sorted(normalizar_texto(s) for s in datos.get("skills_obligatorios") or [])),
        str(datos.get("experience_required") or ""),
        str(datos.get("english_required") or "").upper(),
        str(datos.get("availability_required") or ""),
        normalizar_texto(datos.get("modality") or ""),
    ]
    return hashlib.sha1("\n".join(partes).encode("utf-8")).hexdigest()[:16]


def vacante_nueva(datos: dict, origen: str, fuente: str, motivo: str, advertencias=None) -> dict:
    """Arma la clasificación de una vacante que sí entra a la cola."""

    return {
        "clase": VACANTE_NUEVA,
        "vacante": datos,
        "origen": origen,
        "fuente": fuente,
        "motivo": motivo,
        "advertencias": list(advertencias or []),
    }


def _revision(datos: dict | None, origen: str, fuente: str, problemas: list[str]) -> dict:
    return {
        "clase": REVISION_HUMANA,
        "vacante": None,
        "datos": datos or {},
        "origen": origen,
        "fuente": fuente,
        "motivo": (
            "El correo parece una vacante pero no alcanza para el matching: "
            + "; ".join(problemas)
        ),
        "problemas": problemas,
        "advertencias": [],
    }


def _no_relacionado(tipo: str, fuente: str, motivo: str, advertencias=None) -> dict:
    return {
        "clase": NO_RELACIONADO,
        "vacante": None,
        "tipo_texto": tipo,
        "origen": "",
        "fuente": fuente,
        "motivo": motivo,
        "advertencias": list(advertencias or []),
    }


def revisar_estructura(correo: dict) -> list[str]:
    """Incoherencias entre la vacante estructurada y el texto del correo.

    La estructura manda (es la que se procesa), pero si el texto pide otra
    cosa, el correo se marca para revisión: el mismo puesto daría resultados
    distintos según el origen (RF-16).
    """

    estructurada = correo.get("vacante_estructurada")
    if not isinstance(estructurada, dict):
        return []

    texto = str(correo.get("cuerpo") or "")
    if not texto.strip():
        return []

    del_texto = interpretar_vacante(texto, [], hoy=_fecha_del_correo(correo)).datos
    # La fecha relativa ("en 2 semanas") no se compara: depende del día de
    # llegada y no dice que la vacante sea otra.
    fecha_relativa = "semanas" in normalizar_texto(texto)
    problemas = []

    skills_texto = {
        normalizar_texto(skill) for skill in del_texto.get("skills_obligatorios") or []
    }
    skills_estructura = {
        normalizar_texto(skill) for skill in estructurada.get("skills_obligatorios") or []
    }
    # El texto de una solicitud detallada nombra obligatorios y deseables
    # juntos ("se requiere X; deseables Y"), así que cuenta contra los dos.
    skills_validas = skills_estructura | {
        normalizar_texto(skill) for skill in estructurada.get("skills_deseables") or []
    }
    if skills_texto and not skills_texto <= skills_validas:
        faltan = sorted(skills_texto - skills_validas)
        problemas.append(
            f"el texto exige {', '.join(faltan)} y la vacante estructurada no"
        )

    for campo in ("experience_required", "english_required", "availability_required", "modality"):
        valor_texto = del_texto.get(campo)
        valor_estructura = estructurada.get(campo)
        if valor_texto in (None, "") or valor_estructura in (None, ""):
            continue
        if campo == "availability_required" and fecha_relativa:
            continue
        if campo == "experience_required":
            igual = int(valor_texto) == int(valor_estructura)
        elif campo == "english_required":
            igual = str(valor_texto).upper() == str(valor_estructura).upper()
        elif campo == "modality":
            igual = normalizar_texto(valor_texto) == normalizar_texto(valor_estructura)
        else:
            igual = str(valor_texto) == str(valor_estructura)
        if not igual:
            problemas.append(
                f"{campo}: el texto dice {valor_texto} y la estructura {valor_estructura}"
            )

    return problemas


def _fecha_del_correo(correo: dict) -> date | None:
    """Fecha de llegada del correo, para resolver 'disponible en 2 semanas'."""

    valor = str(correo.get("timestamp") or correo.get("fecha") or "").strip()
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(valor[:10])
        except ValueError:
            return None


def clasificar_por_reglas(correo: dict) -> dict:
    """Fase 1: clasifica el correo de forma determinista (RF-16)."""

    estructurada = correo.get("vacante_estructurada")
    texto = str(correo.get("cuerpo") or "")
    hoy = _fecha_del_correo(correo)

    # La bandeja simulada trae la vacante armada: manda la estructura.
    if isinstance(estructurada, dict) and estructurada.get("id"):
        return _clasificar_estructurada(estructurada, correo)

    if isinstance(estructurada, dict) and estructurada:
        # Estructura incompleta: se completa con el texto y se manda a revisión
        # si sigue sin rol o sin skills obligatorios.
        datos = {**interpretar_vacante(texto, [], hoy=hoy).datos, **estructurada}
        if tiene_rol_y_skills(datos):
            return vacante_nueva(
                datos,
                "vacante estructurada incompleta + texto",
                FUENTE_REGLAS,
                "La vacante estructurada estaba incompleta; se completó con el texto.",
            )
        return _revision(
            datos,
            "vacante estructurada incompleta de la bandeja",
            FUENTE_REGLAS,
            _problemas_de_vacante(datos),
        )

    interpretado = interpretar(texto, hoy=hoy)

    if interpretado.tipo == TIPO_CANDIDATO:
        return _no_relacionado(
            TIPO_CANDIDATO,
            FUENTE_REGLAS,
            "El correo describe el perfil de un candidato, no una vacante.",
            interpretado.advertencias,
        )

    if interpretado.tipo != TIPO_VACANTE and _es_consulta_de_tramite(texto):
        # Pregunta por el proceso o por "la" contratación, sin decir qué
        # puesto ni para qué: es gestión, no una vacante incompleta.
        return _no_relacionado(
            "desconocido",
            FUENTE_REGLAS,
            "El correo consulta por el proceso de contratación; no describe un "
            "puesto concreto (gestión).",
            interpretado.advertencias,
        )

    if interpretado.tipo != TIPO_VACANTE and _es_solo_gestion(interpretado):
        # Habla de vacantes o de "la" contratación, pero no describe un
        # puesto concreto: es gestión, no una vacante incompleta.
        return _no_relacionado(
            "desconocido",
            FUENTE_REGLAS,
            "El correo habla de vacantes o del proceso de contratación, "
            "pero no describe un puesto concreto (gestión).",
            interpretado.advertencias,
        )

    if interpretado.tipo == TIPO_VACANTE or _es_necesidad_de_contratacion(texto):
        datos = (
            interpretado.datos
            if interpretado.tipo == TIPO_VACANTE
            else interpretar_vacante(texto, interpretado.pistas, hoy=hoy).datos
        )
        datos = _completar_desde_texto(datos, texto, hoy)
        if tiene_rol_y_skills(datos):
            return vacante_nueva(
                datos,
                "texto libre del correo",
                FUENTE_REGLAS,
                "El texto describe un puesto con rol y skills obligatorios.",
                interpretado.advertencias,
            )
        return _revision(
            datos,
            "texto libre del correo",
            FUENTE_REGLAS,
            _problemas_de_vacante(datos),
        )

    return _no_relacionado(
        interpretado.tipo or "desconocido",
        FUENTE_REGLAS,
        "El correo no describe un puesto ni aporta datos de vacante "
        "(gestión, boletín, factura o texto sin señales).",
        interpretado.advertencias,
    )


def _clasificar_estructurada(estructurada: dict, correo: dict) -> dict:
    """Clasifica un correo cuya vacante ya viene armada."""

    from src.solicitud_vacante import CAMPOS_OBLIGATORIOS

    if not tiene_rol_y_skills(estructurada):
        return _revision(
            estructurada,
            "vacante estructurada de la bandeja",
            FUENTE_REGLAS,
            _problemas_de_vacante(estructurada),
        )

    faltantes = CAMPOS_OBLIGATORIOS - set(estructurada)
    if faltantes:
        return _revision(
            estructurada,
            "vacante estructurada de la bandeja",
            FUENTE_REGLAS,
            [f"faltan campos {sorted(faltantes)}"],
        )

    problemas = revisar_estructura(correo)
    if problemas:
        return _revision(
            estructurada,
            "vacante estructurada de la bandeja",
            FUENTE_REGLAS,
            ["el texto del correo no coincide con la vacante"] + problemas,
        )

    return vacante_nueva(
        estructurada,
        "vacante estructurada de la bandeja",
        FUENTE_REGLAS,
        "El correo trae la vacante estructurada válida; entra a la cola.",
    )


def _es_solo_gestion(interpretado) -> bool:
    """Una vacante incompleta describe un cargo; una consulta solo lo menciona.

    "Necesitamos a alguien para soporte" habla de un puesto (va a revisión
    humana); "¿cuál es el proceso para enviar vacantes?" solo pide el trámite.
    """

    datos = interpretado.datos or {}
    return not rol_de_vacante(datos)


def _rol_del_cargo(texto: str) -> str:
    """Cargo concreto nombrado en el texto ("para soporte", "perfil de QA")."""

    base = normalizar_texto(texto)
    coincidencia = re.search(
        r"\b(?:para|de|como|perfil(?: de)?)\s+(?:un |una |el |la )?"
        r"([a-z]+(?: [a-z]+)?)"
        r"(?:[.,;]|\s+(?:que|con|en|para|cuando|y|disponibilidad|presencial|remoto|hibrido))",
        base,
    )
    if not coincidencia:
        return ""

    cargo = coincidencia.group(1).strip()
    if cargo in _PALABRAS_DEL_TRAMITE:
        return ""
    if len(cargo.split()) < 2 and len(cargo) < 5:
        return ""
    return cargo


def _es_consulta_de_tramite(texto: str) -> bool:
    """El correo pregunta *cómo* se hace un trámite, no pide contratar a nadie.

    "¿Cuál es el proceso para enviarles una solicitud?" habla de vacantes,
    pero el remitente es quien pregunta, no quien ofrece un puesto.
    """

    base = normalizar_texto(texto)
    if re.search(
        r"\b(cual es|como (?:es|se hace|puedo)|me indican|me dicen|informacion sobre)\b",
        base,
    ):
        return True
    return bool(re.search(r"\b(?:enviarles|enviar|mandar|compartir)\s+(?:una |la )?solicitud", base))


def _es_necesidad_de_contratacion(texto: str) -> bool:
    """El texto dice que la organización necesita contratar, aunque falten datos."""

    from src.interpretar_texto import _senales_contexto

    senales = _senales_contexto(texto)
    return bool(senales["solicitud"])


def _problemas_de_vacante(datos: dict) -> list[str]:
    """Lista de lo que le falta para poder iniciar el matching."""

    problemas = []
    if not rol_de_vacante(datos):
        problemas.append("no trae el rol del puesto (título)")
    if not [s for s in datos.get("skills_obligatorios") or [] if str(s).strip()]:
        problemas.append("no trae skills obligatorios")
    return problemas


def revisar_datos(datos: dict) -> list[str]:
    """Problemas de esquema de una vacante ya armada (`validar_vacante`).

    Se expone aquí para que el reporte use el mismo criterio que la
    clasificación (RF-11/RF-16).
    """

    from src.solicitud_vacante import validar_vacante

    return validar_vacante(datos)


def _completar_desde_texto(datos: dict, texto: str, hoy: date | None) -> dict:
    """Deja vacíos (no inventados) los campos que el texto no mencionó."""

    completo = dict(datos)
    for campo in ("titulo", "skills_deseables"):
        completo.setdefault(campo, "")
    for campo in ("experience_required", "english_required", "availability_required", "modality"):
        completo.setdefault(campo, None)
    if not completo.get("titulo"):
        completo["titulo"] = interpretar_vacante(texto, [], hoy=hoy).datos.get("titulo") or ""
    completo.setdefault("descripcion", texto.strip())
    completo.setdefault("skills_obligatorios", [])
    completo.setdefault("skills_deseables", [])
    return completo


def clasificar_con_llm(correo: dict, llm) -> dict:
    """Fase 2: el LLM decide la clase y extrae los criterios (RF-16).

    Se le pasa el correo completo y su respuesta se valida en código: si
    dice `vacante_nueva` pero no trae rol ni skills obligatorios, se degrada
    a `revision_humana`; si falla la llamada, se usa la fase 1 por reglas.
    """

    from src.llm_cliente import ErrorLLM, interpretar_correo_con_llm

    hoy = _fecha_del_correo(correo)
    try:
        respuesta = interpretar_correo_con_llm(llm, correo, hoy)
    except ErrorLLM as error:
        clasificado = clasificar_por_reglas(correo)
        clasificado["fuente"] = FUENTE_REGLAS
        clasificado["advertencias"] = clasificado.get("advertencias", []) + [
            f"LLM no disponible, se usaron las reglas: {error}"
        ]
        return clasificado
    except Exception as error:  # red, cuota o modelo inválido
        clasificado = clasificar_por_reglas(correo)
        clasificado["advertencias"] = clasificado.get("advertencias", []) + [
            f"Falló la llamada al LLM, se usaron las reglas: {type(error).__name__}: {error}"
        ]
        return clasificado

    clase = str(respuesta.get("clase") or "").strip()
    llm_calls = respuesta.get("llm_calls", 1)

    if clase == NO_RELACIONADO:
        return {
            **_no_relacionado(
                str(respuesta.get("tipo_texto") or "desconocido"),
                FUENTE_LLM,
                str(respuesta.get("motivo") or "El correo no describe una vacante."),
            ),
            "llm_calls": llm_calls,
        }

    datos = normalizar_vacante_llm(respuesta)
    if not tiene_rol_y_skills(datos):
        return {
            **_revision(
                datos,
                "clasificación del LLM",
                FUENTE_LLM,
                _problemas_de_vacante(datos),
            ),
            "llm_calls": llm_calls,
        }

    # El LLM no decide si entra: solo propone la clase. La cola y los
    # duplicados los resuelve `encolar` en código.
    clase = VACANTE_NUEVA
    return {
        **vacante_nueva(
            datos,
            "clasificación del LLM",
            FUENTE_LLM,
            str(respuesta.get("motivo") or "El LLM identificó una solicitud de vacante."),
        ),
        "clase": clase,
        "llm_calls": llm_calls,
    }


def normalizar_vacante_llm(respuesta: dict) -> dict:
    """Normaliza los campos de la vacante que devolvió el LLM."""

    datos = respuesta.get("vacante")
    if not isinstance(datos, dict):
        datos = {}

    return {
        "id": datos.get("id") or "",
        "titulo": datos.get("titulo") or "",
        "descripcion": datos.get("descripcion") or "",
        "skills_obligatorios": [str(s).strip() for s in datos.get("skills_obligatorios") or [] if str(s).strip()],
        "skills_deseables": [str(s).strip() for s in datos.get("skills_deseables") or [] if str(s).strip()],
        "experience_required": datos.get("experience_required"),
        "english_required": str(datos.get("english_required") or "").upper() or None,
        "availability_required": datos.get("availability_required"),
        "modality": datos.get("modality"),
    }


def modo_de_clasificacion(modo: str | None = None) -> str:
    """Fase activa: respeta el argumento, luego la configuración (RNF-02)."""

    from src.configuracion import cargar_configuracion, normalizar_modo

    if modo:
        return normalizar_modo(modo)
    return cargar_configuracion().modo


def clasificar_correo(correo: dict, modo: str | None = None, llm=None) -> dict:
    """Clasifica un correo en la fase indicada por la configuración (RF-16)."""

    from src.configuracion import MODO_CON_LLM

    fase = modo_de_clasificacion(modo)
    if fase == MODO_CON_LLM:
        return clasificar_con_llm(correo, llm)
    return clasificar_por_reglas(correo)


def clasificar_correo_bandeja(correo: dict) -> dict:
    """Atajo por reglas para la bandeja simulada (RF-15/RF-16)."""

    return clasificar_por_reglas(correo)


# --- cola de vacantes ---


def vacia_cola() -> dict:
    """Estado inicial de la cola."""

    return {"vacantes": [], "duplicados": [], "revision_humana": []}


def cargar_cola(ruta: Path | None = None) -> dict:
    """Lee la cola persistida; si no existe, devuelve una cola vacía."""

    ruta = Path(ruta) if ruta else ARCHIVO_COLA
    if not ruta.exists():
        return vacia_cola()

    with ruta.open("r", encoding="utf-8-sig") as archivo:
        datos = json.load(archivo)

    cola = vacia_cola()
    cola.update({clave: datos.get(clave, []) for clave in cola})
    return cola


def guardar_cola(cola: dict, ruta: Path | None = None) -> Path:
    """Guarda la cola para que el reporte pueda reconstruir la trazabilidad."""

    ruta = Path(ruta) if ruta else ARCHIVO_COLA
    ruta.parent.mkdir(parents=True, exist_ok=True)

    with ruta.open("w", encoding="utf-8") as archivo:
        json.dump(cola, archivo, ensure_ascii=False, indent=2)
        archivo.write("\n")

    return ruta


def _ya_recibida(datos: dict, cola: dict) -> dict | None:
    """Busca la vacante ya recibida que coincide con este correo."""

    for registrada in cola["vacantes"]:
        vacante = registrada.get("vacante") or {}
        if datos.get("id") and vacante.get("id") == datos.get("id"):
            return registrada
        if huella_vacante(vacante) == huella_vacante(datos):
            return registrada
    return None


def encolar(correo: dict, cola: dict, modo: str | None = None, llm=None) -> dict:
    """Clasifica el correo y, si es vacante nueva, la pone en la cola (RF-16).

    Solo `vacante_nueva` entra a la cola y dispara el matching. Un duplicado
    se registra apuntando a la vacante original; las revisiones humanas quedan
    en la cola de revisión para que no se pierdan.

    Devuelve la decisión con la forma de `clasificar_correo` más `en_cola`.
    """

    clasificado = clasificar_correo(correo, modo=modo, llm=llm)
    message_id = str(correo.get("message_id") or "")
    base = {
        "message_id": message_id,
        "origen_tipo": clasificado.get("origen", ""),
        "fuente": clasificado.get("fuente", ""),
        "motivo": clasificado.get("motivo", ""),
        "advertencias": clasificado.get("advertencias", []),
        "errores": clasificado.get("problemas", []),
        "llm_calls": clasificado.get("llm_calls", 0),
        # Reenvío declarado en la bandeja: siempre es duplicado de ese correo.
        "reenvio_de": str(correo.get("reenvio_de") or ""),
    }

    if clasificado["clase"] == VACANTE_NUEVA:
        datos = clasificado["vacante"]
        if not datos.get("id"):
            datos = {**datos, "id": _id_para(correo, cola)}
        anterior = _ya_recibida(datos, cola)
        reenvio = base["reenvio_de"]
        previo = next(
            (r for r in cola["vacantes"] if reenvio and r.get("message_id") == reenvio), None
        )
        previo = previo or anterior
        if previo is not None:
            cola["duplicados"].append(
                {
                    "message_id": message_id,
                    "vacante_id": previo.get("vacante", {}).get("id", ""),
                    "original_message_id": previo.get("message_id", ""),
                }
            )
            return {
                "clase": DUPLICADO,
                "vacante_id": previo.get("vacante", {}).get("id", ""),
                "duplicado_de": previo.get("message_id", ""),
                "disparo_matching": False,
                "en_cola": False,
                **base,
                "motivo": (
                    f"Vacante ya recibida en el correo {previo.get('message_id', '')}; "
                    "no vuelve a la cola."
                ),
            }

        cola["vacantes"].append(
            {
                "vacante": datos,
                "message_id": message_id,
                "origen": clasificado.get("origen", ""),
                "fuente": clasificado.get("fuente", ""),
                "huella": huella_vacante(datos),
            }
        )
        return {
            "clase": VACANTE_NUEVA,
            "vacante_id": datos.get("id", ""),
            "vacante": datos,
            "disparo_matching": True,
            "en_cola": True,
            **base,
        }

    if clasificado["clase"] == REVISION_HUMANA:
        cola["revision_humana"].append(
            {
                "message_id": message_id,
                "datos": clasificado.get("datos") or {},
                "problemas": clasificado.get("problemas", []),
                "motivo": clasificado.get("motivo", ""),
            }
        )
        return {
            "clase": REVISION_HUMANA,
            "vacante_id": (clasificado.get("datos") or {}).get("id", ""),
            "disparo_matching": False,
            "en_cola": False,
            **base,
        }

    if clasificado["clase"] == DUPLICADO:
        return {
            "clase": DUPLICADO,
            "vacante_id": "",
            "disparo_matching": False,
            "en_cola": False,
            **base,
        }

    return {
        "clase": NO_RELACIONADO,
        "vacante_id": "",
        "disparo_matching": False,
        "en_cola": False,
        **base,
    }


def _id_para(correo: dict, cola: dict) -> str:
    """ID estable para una vacante del texto libre: V-timestamp del correo."""

    usado = {r.get("vacante", {}).get("id") for r in cola["vacantes"]}
    valor = str(correo.get("timestamp") or correo.get("fecha") or "")
    base = f"V{valor}" if valor else "VCORREO"
    identificador = base
    contador = 2
    while identificador in usado:
        identificador = f"{base}-{contador}"
        contador += 1
    return identificador


def siguiente_de_cola(cola: dict) -> dict | None:
    """Primera vacante en cola que todavía no se procesó."""

    for registrada in cola["vacantes"]:
        if not registrada.get("procesada"):
            return registrada
    return None


def marcar_procesada(cola: dict, vacante_id: str, resultado: dict | None = None) -> None:
    """Saca la vacante de la cola una vez que corrió el matching."""

    for registrada in cola["vacantes"]:
        if registrada.get("vacante", {}).get("id") == vacante_id:
            registrada["procesada"] = True
            if resultado is not None:
                registrada["resultado"] = resultado
            return


def estado_cola(cola: dict) -> dict:
    """Resumen de la cola para la consola y el reporte."""

    return {
        "vacantes": len(cola["vacantes"]),
        "pendientes": sum(1 for r in cola["vacantes"] if not r.get("procesada")),
        "duplicados": len(cola["duplicados"]),
        "revision_humana": len(cola["revision_humana"]),
    }
