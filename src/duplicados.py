
"""Detección y eliminación de perfiles duplicados de candidatos (RF-09).

Reglas:
- Dos perfiles son duplicados si comparten correo (sin distinguir mayúsculas).
- Dos perfiles son duplicados si comparten el mismo nombre y el mismo teléfono.

Si un perfil coincide por cualquiera de las dos reglas con otro ya conservado,
se descarta. Solo se conserva uno (el primero en el orden del dataset).
"""

from difflib import SequenceMatcher
import re
import unicodedata


def normalizar_texto(valor) -> str:
    """Convierte un valor a texto minúsculo, sin tildes ni espacios sobrantes."""

    if valor is None:
        return ""

    texto = str(valor).strip().casefold()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    texto = re.sub(r"\s+", " ", texto)
    return texto


def normalizar_telefono(valor) -> str:
    """Deja el teléfono solo con sus dígitos."""

    if valor is None:
        return ""

    return re.sub(r"\D", "", str(valor))


def _clave_email(candidato: dict) -> str:
    return normalizar_texto(candidato.get("email"))


def _clave_nombre_telefono(candidato: dict) -> tuple[str, str] | None:
    nombre = normalizar_texto(candidato.get("nombre"))
    telefono = normalizar_telefono(candidato.get("telefono"))

    if not nombre or not telefono:
        return None

    return nombre, telefono


def nombre_similar(nombre_a: str, nombre_b: str, umbral: float = 0.9) -> bool:
    """Indica si dos nombres normalizados son prácticamente iguales."""

    if nombre_a == nombre_b:
        return True

    return SequenceMatcher(None, nombre_a, nombre_b).ratio() >= umbral


def buscar_duplicado(
    candidato: dict,
    perfiles_validos: list[dict],
) -> tuple[dict | None, str]:
    """Busca con qué perfil válido choca un candidato.

    Devuelve una tupla (perfil_reportado, motivo). Si no hay duplicado,
    devuelve (None, "").
    """

    email = _clave_email(candidato)
    nombre_telefono = _clave_nombre_telefono(candidato)
    nombre = normalizar_texto(candidato.get("nombre"))

    # Coincidencia por ambas reglas a la vez: se informa el motivo completo.
    for valido in perfiles_validos:
        mismo_email = email and _clave_email(valido) == email
        mismo_perfil = (
            nombre_telefono is not None
            and _clave_nombre_telefono(valido) == nombre_telefono
        )

        if mismo_email and mismo_perfil:
            return valido, "Mismo correo, nombre y teléfono"

    # Coincidencias exactas por correo (teléfono distinto o vacío).
    for valido in perfiles_validos:
        if email and _clave_email(valido) == email:
            return valido, "Mismo correo"

    # Coincidencias exactas por nombre + teléfono (correo distinto o vacío).
    if nombre_telefono is not None:
        for valido in perfiles_validos:
            if _clave_nombre_telefono(valido) == nombre_telefono:
                return valido, "Mismo nombre y teléfono"

    # Coincidencias por nombre muy similar + correo parecido
    # (por ejemplo, distinta escritura de tildes o del nombre).
    if email:
        usuario_email = email.split("@", 1)[0]
        for valido in perfiles_validos:
            _clave_valido = _clave_email(valido)
            if not _clave_valido:
                continue

            usuario_valido = _clave_valido.split("@", 1)[0]
            if (
                nombre
                and nombre_similar(nombre, normalizar_texto(valido.get("nombre")))
                and nombre_similar(usuario_email, usuario_valido)
            ):
                return valido, "Mismo correo y mismo nombre (escritura equivalente)"

    return None, ""


def depurar_duplicados(
    candidatos: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Elimina los perfiles duplicados dejando un solo perfil por persona.

    Devuelve (validos, duplicados):
    - validos: perfiles únicos que se procesan en el matching.
    - duplicados: perfiles descartados con el motivo de su descarte.
    """

    validos: list[dict] = []
    duplicados: list[dict] = []

    for indice, candidato in enumerate(candidatos, start=1):
        # Dos nombres distintos sin correo ni teléfono no son la misma persona:
        # los perfiles que llegan por correo suelen traer esos campos vacíos.
        nombre = normalizar_texto(candidato.get("nombre"))
        sin_contacto = not _clave_email(candidato) and not normalizar_telefono(
            candidato.get("telefono")
        )
        if nombre and sin_contacto:
            mismo_nombre = next(
                (
                    valido
                    for valido in validos
                    if normalizar_texto(valido.get("nombre")) == nombre
                ),
                None,
            )
            if mismo_nombre is not None:
                duplicados.append(
                    {
                        "id": candidato.get("id", ""),
                        "nombre": candidato.get("nombre", ""),
                        "email": candidato.get("email", ""),
                        "telefono": candidato.get("telefono", ""),
                        "posicion": indice,
                        "conservado_id": mismo_nombre.get("id", ""),
                        "motivo": "Mismo nombre sin datos de contacto",
                    }
                )
                continue
            validos.append(candidato)
            continue

        reportado, motivo = buscar_duplicado(candidato, validos)

        if reportado is not None:
            duplicados.append(
                {
                    "id": candidato.get("id", ""),
                    "nombre": candidato.get("nombre", ""),
                    "email": candidato.get("email", ""),
                    "telefono": candidato.get("telefono", ""),
                    "posicion": indice,
                    "conservado_id": reportado.get("id", ""),
                    "motivo": motivo,
                }
            )
            continue

        validos.append(candidato)

    return validos, duplicados
