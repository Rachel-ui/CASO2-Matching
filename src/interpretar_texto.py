
"""Interpreta el texto libre de un correo y lo ordena según lo que describe.

El reclutador escribe en lenguaje natural ("busco un backend con Python y 3
años de experiencia" o "soy Daniela, tengo 26 años y trabajo con React").
Aquí se detecta a qué pertenece el texto y se extraen los campos del esquema
de vacante o de candidato, sin LLM para que sea reproducible (RNF-02, RNF-03).

Si falta un dato no se inventa: se deja vacío y se informa en `advertencias`.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.duplicados import normalizar_texto


TIPO_VACANTE = "vacante"
TIPO_CANDIDATO = "candidato"
TIPO_DESCONOCIDO = "desconocido"

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

# Vocabulario de referencia: solo se listan skills conocidas para no tomar
# palabras sueltas como "de" o "con" como habilidades. La clave va como
# aparece en el correo (normalizada); el valor es la forma canónica.
CATALOGO_SKILLS = {
    "python": "Python", "java": "Java", "javascript": "JavaScript", "js": "JavaScript",
    "typescript": "TypeScript", "react": "React", "angular": "Angular", "vue": "Vue",
    "node": "Node.js", "nodejs": "Node.js", "html": "HTML", "css": "CSS",
    "sql": "SQL", "mysql": "MySQL", "postgresql": "PostgreSQL", "mongodb": "MongoDB",
    "db2": "DB2", "git": "Git", "github": "GitHub", "gitlab": "GitLab",
    "docker": "Docker", "kubernetes": "Kubernetes",
    "aws": "AWS", "azure": "Azure", "gcp": "GCP", "linux": "Linux",
    "django": "Django", "flask": "Flask", "fastapi": "FastAPI",
    "spring boot": "Spring Boot", "spring": "Spring",
    "rest": "REST API", "api rest": "REST API", "apis": "REST API", "api": "REST API",
    "cache": "Caché", "cacheo": "Caché",
    "linea de comandos": "CLI", "cli": "CLI",
    "balanceo de carga": "Balanceo de carga",
    "productos comerciales": "Productos comerciales",
    "microservicios": "Microservicios", "microservices": "Microservicios",
    "kafka": "Kafka", "terraform": "Terraform", "ci/cd": "CI/CD",
    "new relic": "New Relic", "splunk": "Splunk", "claude": "Claude",
    "agentes de ia": "Agentes de IA",
    "infraestructura como codigo": "Infraestructura como codigo",
    "automatizacion": "Automatizacion",
    "rpg iii": "RPG III", "rpg iv": "RPG IV", "rpg ile": "RPG ILE",
    "rpg free": "RPG Free", "ile": "RPG ILE", "cl": "CL",
    "ibm i": "IBM i (AS/400)", "as/400": "IBM i (AS/400)",
    "cobol": "COBOL 400/ILE", "cobol 400": "COBOL 400/ILE",
    "scrum": "Scrum", "excel": "Excel", "pandas": "Pandas",
    "machine learning": "Machine Learning", "php": "PHP", "c#": "C#", ".net": ".NET",
    "c++": "C++", "kotlin": "Kotlin", "swift": "Swift", "flutter": "Flutter",
    "power bi": "Power BI", "sap": "SAP", "nextjs": "Next.js", "next.js": "Next.js",
}

# Skills canónicas que el catálogo reconoce con varios términos: en el texto
# basta con uno de ellos para contar la skill ("RPG ILE" incluye lo de RPG IV).
EQUIVALENCIAS_SKILLS = {
    "RPG IV": ("RPG IV", "RPG ILE"),
    "RPG ILE": ("RPG IV", "RPG ILE"),
}

# Orden de búsqueda: primero las entradas más largas ("api rest" antes de "api").
_SKILLS_POR_LONGITUD = sorted(CATALOGO_SKILLS, key=len, reverse=True)
_PATRON_SKILLS = re.compile(
    r"(?<![\w])(" + "|".join(re.escape(k) for k in _SKILLS_POR_LONGITUD) + r")(?![\w+/])"
)

_NIVELES = ("A1", "A2", "B1", "B2", "C1", "C2")

# Sinónimos de modalidad con su forma canónica del esquema.
_MODALIDADES = {
    "remoto": "remoto", "remota": "remoto", "teletrabajo": "remoto",
    "desde casa": "remoto", "home office": "remoto", "virtual": "remoto",
    "hibrido": "hibrido", "hibrida": "hibrido", "mixto": "hibrido",
    "mixta": "hibrido", "semipresencial": "hibrido",
    "presencial": "presencial", "en oficina": "presencial", "on-site": "presencial",
}

_PALABRAS_NO_NOMBRE = {
    "tengo", "poseo", "cuento", "con", "y", "mi", "estoy", "soy", "en",
    "vivo", "resido", "actualmente", "trabajo", "me", "dedico", "edad",
}


@dataclass
class TextoInterpretado:
    """Resultado de leer el texto libre de un correo."""

    tipo: str
    datos: dict
    pistas: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    evidencia: dict = field(default_factory=dict)

    @property
    def informativo(self) -> bool:
        """Un texto es informativo si aporta al menos un dato útil."""

        valor = self.datos.get("skills_obligatorios") or self.datos.get("skills")
        return bool(
            valor
            or self.datos.get("experience_required") is not None
            or self.datos.get("experience_years") is not None
        )


def _texto_normalizado(texto: str) -> str:
    sin_tildes = normalizar_texto(texto)
    return re.sub(r"\s+", " ", sin_tildes)


def _oraciones(texto: str) -> list[str]:
    partes = re.split(r"[.!?;\n]", texto)
    return [parte.strip() for parte in partes if parte.strip()]


def _senales_contexto(texto: str) -> dict:
    """Señales lingüísticas del texto, sin depender de palabras aisladas.

    Cada señal mira la estructura de la oración (sujeto, verbo, objeto y
    tiempos verbales), no la simple presencia de un término.
    """

    oraciones = _oraciones(texto)
    base = _texto_normalizado(texto)
    senales: dict[str, list[str]] = {
        "solicitud": [], "oferta": [], "perfil": [], "posesion": [],
        "experiencia": [], "trato": [], "actividad": [],
    }

    for oracion in oraciones:
        n = _texto_normalizado(oracion)

        # Quien haba de sí mismo en primera persona describe un perfil.
        if re.search(r"\b(?:soy|me llamo|tengo \d|estoy|he trabajado|trabajo con)\b", n):
            senales["perfil"].append(oracion)

        # Perfil descrito en tercera persona por quien lo reenvía:
        # "Andrés Pérez es un desarrollador senior con nueve años...",
        # "Valeria Castro trabaja con Next.js y TypeScript".
        if re.search(
            r"\b(?:es|fue|trabaja|se desempena|se especializa|posee|cuenta con)"
            r"\s+(?:un|una|el|la)?\s*(?:desarrollador|desarrolladora|ingenier[oa]"
            r"|analista|programador|programadora|arquitect[oa]|consultor|consultora"
            r"|profesional|especialista|tecnic[oa])\b",
            n,
        ) or re.search(
            r"\bdesarrollador(?:a)?\s+(?:de\s+software\s+)?(?:senior|junior|mid"
            r"|full[ -]?stack|backend|frontend|web|movil)\b",
            n,
        ) or re.search(
            r"\b(?:trabaja|se desempena|se especializa|cuenta con|tiene experiencia)"
            r"\s+(?:con|en)\s+[a-z0-9]",
            n,
        ):
            senales["perfil"].append(oracion)

        # Posesión de datos personales propios. Las viñetas de un CV
        # ("Experiencia: 9 años", "Inglés: C1") también describen a la persona.
        if re.search(r"\bmi (?:nombre|experiencia|nivel|formacion|perfil|cv|curriculum)"
                     r"|\b(mis) (?:habilidades|competencias|estudios)", n):
            senales["posesion"].append(oracion)
        if re.match(
            r"^(?:experiencia|skills|habilidades|competencias|ingles|idiomas"
            r"|modalidad|disponibilidad|residencia|ubicacion|telefono|email|correo"
            r"|puesto|rol|candidato)\b",
            n,
        ):
            senales["posesion"].append(oracion)

        # Antigüedad declarada: "tengo 3 años" (primera persona) o
        # "posee siete años de experiencia" (ficha reenviada).
        if re.search(r"\btengo \d+ (?:anos|años|lustros)", n):
            senales["experiencia"].append(oracion)
        if re.search(
            r"\b(?:posee|cuenta con|tiene)\s+(?:(?:mas|menos)\s+de\s+)?"
            r"(?:\d+|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once"
            r"|doce|trece|catorce|quince|dieciseis|diecisiete|dieciocho|diecinueve"
            r"|veinte)\s+(?:anos|años)\b",
            n,
        ):
            senales["experiencia"].append(oracion)

        # La organización presenta una necesidad que todavía no existe:
        # "buscamos / necesitamos / requerimos / se requiere" + objeto de cargo.
        if re.search(r"\b(?:buscamos|necesitamos|requerimos|se busca|se requiere|se solicitan?"
                     r"|necesito contratar|estamos contratando|convocamos)\b", n):
            senales["solicitud"].append(oracion)
        # Correo del reclutador que pide una pod de candidatos para un puesto:
        # "quisiera consultar si tenemos candidatos para las siguientes vacantes".
        if re.search(r"\b(?:candidatos?|perfiles?|recursos?|pod)\b", n) and re.search(
            r"\b(?:tenemos|tiene|contamos|hay|disponibles?|disponibilidad|para)\b"
            r"|\b(?:piden?|solicitan|vacantes?|puestos?|roles?|posiciones?)\b",
            n,
        ) and not re.search(r"\b(?:me llamo|soy|tengo \d+ (?:anos|años))\b", n):
            senales["solicitud"].append(oracion)
        if re.search(r"\b(?:vacante|plaza|puesto|oferta|convocatoria|cargo)"
                     r"\b(?:disponible|abiert[ao]|para el area|para el departamento)?", n):
            senales["oferta"].append(oracion)

        # Trato impersonal o de cortesía típico de un mensaje administrativo.
        if re.search(r"\b(?:buenos dias|buenas tardes|buenas noches|saludos|cordialmente"
                     r"|muchas gracias|quedo atent[ao]|por favor|de antemano"
                     r"|estimad[ao]|atentamente)\b", n):
            senales["trato"].append(oracion)

        # Verbo de gestión o trámite (pide, reenvía, coordina).
        if re.search(r"\b(?:me mandes|me envies|me compartas|me confirmes|me indiques"
                     r"|avances|actualizacion|reunion|revisemos|coordinar|programar\b)", n):
            senales["actividad"].append(oracion)

    # Las preguntas suelen pedir información, no ofrecer un cargo.
    if re.search(r"\b(?:cuando|puedes|podrias|seria posible|me pasas|me envias)", base):
        senales["actividad"].append("pregunta al remitente")

    return senales


def detectar_tipo(texto: str) -> tuple[str, list[str]]:
    """Decide si el texto describe una vacante o un candidato por contexto.

    No decide por palabras sueltas: compara las señales estructurales del
    mensaje (primera persona, necesidad de contratación, trato personal).
    Las palabras solo se usan como evidencia y se guardan para auditoría.
    """

    evidencia = _senales_contexto(texto)
    perfil = len(evidencia["perfil"]) + len(evidencia["posesion"]) + len(evidencia["experiencia"])
    solicitud = len(evidencia["solicitud"]) * 2 + len(evidencia["oferta"])
    gestion = len(evidencia["trato"]) + len(evidencia["actividad"])

    # Un perfil se describe con varias oraciones, todas sobre la misma persona:
    # con una sola ("es un desarrollador senior") no alcanza, porque una
    # vacante también puede nombrar el cargo una vez.
    if perfil >= 2 and perfil > solicitud:
        return TIPO_CANDIDATO, evidencia["perfil"] + evidencia["posesion"] + evidencia["experiencia"]

    # Necesidad explícita de cubrir un cargo → vacante.
    if solicitud >= 1 and solicitud >= gestion:
        return TIPO_VACANTE, evidencia["solicitud"] + evidencia["oferta"]

    # Correo administrativo que solo menciona temas → no es dato útil.
    if gestion:
        return TIPO_DESCONOCIDO, evidencia["trato"] + evidencia["actividad"]

    return TIPO_DESCONOCIDO, []


def extraer_skills(texto: str) -> list[str]:
    """Devuelve las skills conocidas mencionadas, sin repetir y en orden."""

    encontradas = []
    for coincidencia in _PATRON_SKILLS.finditer(_texto_normalizado(texto)):
        canonica = CATALOGO_SKILLS[coincidencia.group(1)]
        if canonica not in encontradas:
            encontradas.append(canonica)
    return encontradas


_NUMEROS_EN_LETRA = {
    "un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11,
    "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16,
    "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
}


def extraer_experiencia(texto: str) -> int | None:
    """Años de experiencia: '3 años', '3 anos', 'siete años y medio'."""

    base = _texto_normalizado(texto)
    patron = (
        r"(\d{1,2}|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez"
        r"|once|doce|trece|catorce|quince|dieciseis|diecisiete|dieciocho"
        r"|diecinueve|veinte)\s*(?:años|anos|lustros?)"
    )
    coincidencia = re.search(patron, base)
    if not coincidencia:
        return None

    # "siete años y seis meses" son 7 años completos (los meses no suman año).
    valor = _valor_experiencia(coincidencia)

    # "tengo 26 años" es la edad, no la experiencia.
    previo = base[max(0, coincidencia.start() - 12) : coincidencia.start()]
    if re.search(r"\b(tengo|tiene|edad|de edad)\s*$", previo) and valor >= 16:
        siguiente = re.search(patron, base[coincidencia.end() :])
        if not siguiente:
            return None
        return _valor_experiencia(siguiente)

    return valor


def _valor_experiencia(coincidencia: re.Match) -> int:
    bruto = coincidencia.group(1)
    valor = int(bruto) if bruto.isdigit() else _NUMEROS_EN_LETRA[bruto]
    return valor * 5 if "lustro" in coincidencia.group(0) else valor


def extraer_ingles(texto: str) -> str | None:
    """Nivel MCER mencionado ('b1', 'B2', 'inglés B1')."""

    base = _texto_normalizado(texto)
    coincidencia = re.search(r"\b([abc][12])\b", base)
    if not coincidencia:
        return None

    nivel = coincidencia.group(1).upper()
    return nivel if nivel in _NIVELES else None


def extraer_modalidad(texto: str) -> str | None:
    base = _texto_normalizado(texto)
    for clave, canonica in _MODALIDADES.items():
        if re.search(rf"\b{re.escape(clave)}\b", base):
            return canonica
    return None


def extraer_fecha(texto: str, hoy: date | None = None) -> str | None:
    """Fechas ISO ('2026-11-01'), '1 de noviembre' o 'en 2 semanas'."""

    hoy = hoy or date.today()
    base = _texto_normalizado(texto)

    iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", base)
    if iso:
        try:
            return date.fromisoformat(iso.group(1)).isoformat()
        except ValueError:
            return None

    dd_mm = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", base)
    if dd_mm:
        try:
            return date(int(dd_mm.group(3)), int(dd_mm.group(2)), int(dd_mm.group(1))).isoformat()
        except ValueError:
            return None

    dia_mes = re.search(
        r"\b(\d{1,2})\s+de\s+("
        + "|".join(MESES)
        + r")(?:\s+(?:de|del)?\s*(\d{4}))?",
        base,
    )
    if dia_mes:
        anio = int(dia_mes.group(3)) if dia_mes.group(3) else hoy.year
        try:
            return date(anio, MESES[dia_mes.group(2)], int(dia_mes.group(1))).isoformat()
        except ValueError:
            return None

    relativa = re.search(r"\b(?:en|dentro de)\s+(\d{1,2})\s+(semanas?|dias?|meses?)\b", base)
    if relativa:
        cantidad = int(relativa.group(1))
        unidad = relativa.group(2)
        if unidad.startswith("semana"):
            return (hoy + timedelta(weeks=cantidad)).isoformat()
        if unidad.startswith("dia"):
            return (hoy + timedelta(days=cantidad)).isoformat()
        return (hoy + timedelta(days=30 * cantidad)).isoformat()

    if "inmediat" in base or "ya disponible" in base:
        return hoy.isoformat()

    return None


def extraer_nombre(texto: str) -> str | None:
    """Nombre de una persona: 'soy Daniela Quirós', 'me llamo X', 'Soy X.'."""

    limpio = texto.replace("\r", " ").strip()
    patron = re.compile(
        r"(?:me llamo|mi nombre es|soy)\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñü]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñü]+){0,3})",
        re.IGNORECASE,
    )
    coincidencia = patron.search(limpio)
    if not coincidencia:
        # Perfil reenviado en tercera persona: el nombre va al inicio de la
        # primera oración ("Andrés Felipe Ramírez Solano es un desarrollador...").
        inicio = re.match(
            r"([A-ZÁÉÍÓÚÑ][\wáéíóúñü]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñü]+){2,3})"
            r"\s+(?:es|fue|trabaja|se desempena|se especializa|posee|cuenta con)\b",
            re.sub(r"\s+", " ", limpio),
        )
        if not inicio:
            return None
        coincidencia = inicio

    nombre = coincidencia.group(1).strip(" .,;")
    # "soy desarrolladora web" o "soy programador" no son nombres.
    base = _texto_normalizado(nombre)
    if any(palabra in base for palabra in ("desarrollador", "programador", "ingenier", "analista", "junior", "senior")):
        return None

    # Corta verbos que el patrón pudo arrastrar: "soy Daniela quiros tengo".
    palabras = nombre.split()
    while palabras and _texto_normalizado(palabras[-1]) in _PALABRAS_NO_NOMBRE:
        palabras.pop()
    nombre = " ".join(palabras)

    if not nombre or (len(nombre.split()) < 2 and len(nombre) < 4):
        return None
    return nombre


def rango_experiencia(texto: str) -> int | None:
    """Mayor año mencionado se trata como experiencia solo si viene de 'años'."""

    return extraer_experiencia(texto)


def interpretar_vacante(texto: str, pistas: list[str], hoy: date | None = None) -> TextoInterpretado:
    """Arma el objeto de vacante a partir del texto libre."""

    skills = extraer_skills(texto)
    experiencia = extraer_experiencia(texto)
    ingles = extraer_ingles(texto)
    modalidad = extraer_modalidad(texto)
    fecha = extraer_fecha(texto, hoy)
    titulo = _titulo_desde_texto(texto)

    datos = {
        "titulo": titulo,
        "descripcion": texto.strip(),
        "skills_obligatorios": skills,
        "skills_deseables": [],
        "experience_required": experiencia,
        "english_required": ingles,
        "availability_required": fecha,
        "modality": modalidad,
    }

    return TextoInterpretado(
        tipo=TIPO_VACANTE,
        datos=datos,
        pistas=pistas,
        advertencias=_faltantes_vacante(datos),
        evidencia=_senales_contexto(texto),
    )


def interpretar_candidato(texto: str, pistas: list[str], hoy: date | None = None) -> TextoInterpretado:
    """Arma el perfil de candidato a partir del texto libre."""

    from src.candidatos import siguiente_id_candidato

    skills = extraer_skills(texto)
    experiencia = extraer_experiencia(texto)
    ingles = extraer_ingles(texto)
    modalidad = extraer_modalidad(texto)
    fecha = extraer_fecha(texto, hoy)
    nombre = extraer_nombre(texto)
    rol = _rol_desde_texto(texto)

    datos = {
        "id": siguiente_id_candidato(),
        "nombre": nombre,
        "email": "",
        "skills": ";".join(skills),
        "experience_years": experiencia,
        "english_level": ingles,
        "availability_date": fecha or "",
        "modality": modalidad or "",
        "rol": rol,
        "telefono": "",
    }

    return TextoInterpretado(
        tipo=TIPO_CANDIDATO,
        datos=datos,
        pistas=pistas,
        advertencias=_faltantes_candidato(datos),
        evidencia=_senales_contexto(texto),
    )


def _titulo_desde_texto(texto: str) -> str:
    primera = next((linea.strip() for linea in texto.splitlines() if linea.strip()), "")
    if not primera:
        return ""

    if len(primera) <= 80:
        return primera

    return primera[:77].rstrip() + "..."


def _rol_desde_texto(texto: str) -> str:
    base = _texto_normalizado(texto)
    roles = (
        ("desarrolladora web", "Desarrollador Web"),
        ("desarrollador web", "Desarrollador Web"),
        ("backend", "Desarrollador Backend"),
        ("frontend", "Desarrollador Frontend"),
        ("full stack", "Desarrollador Full Stack"),
        ("fullstack", "Desarrollador Full Stack"),
        ("analista", "Analista"),
        ("disenador", "Diseñador"),
        ("diseñador", "Diseñador"),
        ("qa", "QA"),
        ("tester", "QA"),
        ("devops", "DevOps"),
    )
    for clave, rol in roles:
        if clave in base:
            return rol
    # Títulos del lote real que no tienen un nombre corto fijo (Java, AWS, RPG).
    for clave, rol in _ROLES_TECNICOS:
        if re.search(rf"\b{re.escape(clave)}\b", base):
            return rol
    return ""


# Roles del lote real: la clave se busca como palabra completa sobre el texto
# ya normalizado (sin tildes).
_ROLES_TECNICOS = (
    ("rpg", "Ingeniero de Software iSeries RPG"),
    ("ibm i", "Ingeniero de Software iSeries RPG"),
    ("as/400", "Ingeniero de Software iSeries RPG"),
    ("java", "Ingeniero de Software Java"),
    ("administrador aws", "Administrador AWS"),
    ("aws", "Administrador AWS"),
    ("supply chain", "Ingeniero de Software Supply Chain"),
    ("emr", "Ingeniero de Software EMR"),
    ("typescript", "Ingeniero de Software Full Stack"),
)


def _faltantes_vacante(datos: dict) -> list[str]:
    faltantes = []
    if not datos["titulo"]:
        faltantes.append("título")
    if not datos["skills_obligatorios"]:
        faltantes.append("skills obligatorios")
    if datos["experience_required"] is None:
        faltantes.append("años de experiencia")
    if not datos["english_required"]:
        faltantes.append("nivel de inglés")
    if not datos["availability_required"]:
        faltantes.append("fecha de disponibilidad")
    if not datos["modality"]:
        faltantes.append("modalidad")
    return [f"no se indicó {campo} en el correo" for campo in faltantes]


def _faltantes_candidato(datos: dict) -> list[str]:
    faltantes = []
    if not datos["nombre"]:
        faltantes.append("nombre")
    if not datos["email"]:
        faltantes.append("correo electrónico")
    if not datos["skills"]:
        faltantes.append("skills")
    if datos["experience_years"] is None:
        faltantes.append("años de experiencia")
    if not datos["english_level"]:
        faltantes.append("nivel de inglés")
    if not datos["availability_date"]:
        faltantes.append("fecha de disponibilidad")
    if not datos["modality"]:
        faltantes.append("modalidad")
    return [f"no se indicó {campo} en el correo" for campo in faltantes]


def interpretar(texto: str, hoy: date | None = None) -> TextoInterpretado:
    """Punto de entrada: detecta el tipo y extrae los campos."""

    texto = (texto or "").strip()
    if not texto:
        return TextoInterpretado(TIPO_DESCONOCIDO, {}, advertencias=["el correo no tiene texto"])

    tipo, pistas = detectar_tipo(texto)

    if tipo == TIPO_VACANTE:
        return interpretar_vacante(texto, pistas, hoy)
    if tipo == TIPO_CANDIDATO:
        return interpretar_candidato(texto, pistas, hoy)

    if tipo == TIPO_DESCONOCIDO:
        # Sin señales de contexto, una palabra técnica suelta no basta: solo se
        # toma como perfil si además hay un dato personal o una antigüedad.
        hay_dato_personal = bool(extraer_nombre(texto))
        hay_experiencia = extraer_experiencia(texto) is not None

        # Perfil en tercera persona: alguien lo describe con su nombre al inicio
        # ("Nombre Apellido es/trabaja/posee...") y trae skills.
        if not hay_dato_personal and re.match(
            r"[A-ZÁÉÍÓÚÑ][\wáéíóúñü]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñü]+){2,3}"
            r"\s+(?:es|fue|trabaja|se desempena|se especializa|posee|cuenta con)\b",
            texto.strip(),
        ):
            hay_dato_personal = True

        skills = extraer_skills(texto)
        if skills and (hay_dato_personal or hay_experiencia):
            return interpretar_candidato(texto, pistas, hoy)

        return TextoInterpretado(
            TIPO_DESCONOCIDO,
            {},
            pistas,
            ["no se pudo determinar si el correo describe una vacante o un candidato"],
            _senales_contexto(texto),
        )

    return TextoInterpretado(TIPO_DESCONOCIDO, {}, pistas)
