# CASO2-Matching

Agente de matching entre candidatos y vacantes con lectura de solicitudes
desde una bandeja de [AgentMail](https://agentmail.to).

## Requisitos

- Python 3.11+
- Dependencias: `pip install -r requirements.txt`
- Archivo `.env` en la raíz (no se sube al repo, RNF-09):

```
AGENTMAIL_API_KEY=am_...
AGENTMAIL_INBOX_ID=tu-bandeja@agentmail.to
AGENTE_MODO=without_llm
OPENROUTER_API_KEY=...        # solo si AGENTE_MODO usa LLM
```

## Agente de matching

```powershell
# Ejecuta una vacante y deja shortlist, auditoría y respuesta en reports/
python -m src.ejecutar_matching V001
python -m src.ejecutar_matching V002 --salida reports/salida_V002.json
```

Cada corrida deja:

| Archivo | Contenido |
|---|---|
| `reports/shortlist_<id>.csv` | Los perfiles que ocupan puesto, con puntaje y justificación |
| `reports/auditoria_<id>.csv` | Log de auditoría: iteración, nodo, decisión y motivo (RF-10) |
| `reports/salida_<id>.json` | Respuesta del agente: éxito, relajaciones y consultas (RF-17) |

Flujo del grafo (`src/grafo_matching.py`):

```
validar_estado -> depurar_duplicados -> consultar_reclutador
   -> procesar_candidato (loop) -> decidir_siguiente_paso
   -> generar_shortlist -> evaluar_resultado
        -> [éxito] finalizar
        -> [insuficientes] relajar_criterios -> procesar_candidato ...
```

| Nodo | Requisito | Qué hace |
|---|---|---|
| `validar_estado` | RNF-02 | Carga la configuración y el modo de ejecución |
| `depurar_duplicados` | RF-09 | Deja un solo perfil por persona |
| `consultar_reclutador` | RF-04 | Pregunta la fecha faltante al reclutador simulado (`data/reclutador.json`), hasta `recruiter.max_queries` preguntas |
| `procesar_candidato` | RF-03 | Puntúa de 0 a 100 en código y justifica con plantilla |
| `generar_shortlist` | RF-02 | Solo ocupan puesto quienes cumplen todos los requisitos duros y el umbral |
| `evaluar_resultado` | RF-05 | Éxito si al menos 3 candidatos superan el umbral |
| `relajar_criterios` | RF-06 | Mueve la fecha 2 semanas, luego acepta 1 año menos, luego 1 nivel menos de inglés |

### Regla de puntuación (100 puntos)

| Componente | Puntos | Cómo se calcula |
|---|---|---|
| Skills obligatorios | 50 | Proporcional a los skills obligatorios que cumple |
| Skills deseables | 20 | Proporcional a los skills deseables que cumple |
| Experiencia | 15 | 15 si cumple los años; 8 si le falta 1 año; 0 si le faltan más |
| Inglés | 10 | 10 si cumple el nivel; 5 si está un nivel abajo; 0 si está más abajo |
| Disponibilidad | 5 | 5 si está disponible antes de la fecha de inicio; 0 si no o si se desconoce |

Los pesos se cambian en `data/config.yaml`. **Los skills obligatorios no se
relajan nunca**; las relajaciones siguen el orden de `relaxation.order` y se
aplican un máximo de `relaxation.max_relaxations` veces. Si la vacante no se
completa, termina con `estado: incompleta` y `requiere_revision_humana`.

### Datos de prueba

| Archivo | Contenido |
|---|---|
| `data/candidatos.csv` | 40 perfiles ficticios (+ duplicados como control de RF-09) |
| `data/vacantes.json` | Las 3 vacantes de prueba: fácil, media y difícil |
| `data/bandeja.json` | 9 correos simulados en 24 h, con `vacante_estructurada` |
| `data/reclutador.json` | Respuestas del reclutador, incluida una "no se sabe" |
| `data/config.yaml` | Pesos, umbral, orden de relajación, límites y modo |
| `data/salida.json` | Bandeja de salida donde el agente deja la respuesta (RF-17) |

## Correos (AgentMail)

```powershell
# Ver las solicitudes de vacante detectadas
python -m src.leer_correos

# Ver todos los últimos correos
python -m src.leer_correos --todas --limite 5

# Ver el cuerpo completo de uno
python -m src.leer_correos --ver <message_id>

# Vigilar la bandeja hasta que llegue un correo nuevo
python -m src.leer_correos --esperar --intervalo 15

# Vigilar como máximo 10 minutos
python -m src.leer_correos --esperar --tiempo-maximo 600
```
`--esperar` consulta la bandeja periódicamente y termina en cuanto aparece un
mensaje que no existía al iniciar la vigilancia. El intervalo mínimo es de
15 segundos para no agotar la cuota del plan free. Los errores de red se
reintentan hasta 5 veces seguidas antes de abortar.

Códigos de salida: `0` correo nuevo mostrado, `1` error de AgentMail,
`2` sin novedades al vencer `--tiempo-maximo`, `130` cancelado con Ctrl+C.

## Pruebas

```powershell
python -m pytest -q
```

Las pruebas de AgentMail usan `httpx.MockTransport`, así que no consumen cuota.

## Vacantes que llegan por correo

```powershell
# Vigilancia continua: cada correo nuevo se procesa automáticamente
python -m src.leer_correos --vigilar --intervalo 15
```

Por cada correo nuevo:

1. `src/solicitud_vacante.py` extrae la vacante del **cuerpo** (buscando el
   JSON, aunque venga con texto alrededor) o de un **adjunto** `.json`/`.csv`.
2. Se valida con el mismo esquema de `data/vacantes.json`. Si llega completa
   con otro `id`, se agrega; si repite un `id`, se actualiza.
3. `src/procesar_correo.py` guarda la vacante en `data/vacantes.json` y
   archiva el correo original en `data/vacantes_correo/<id>.json`.
4. Se ejecuta el agente de matching y se escriben
   `reports/shortlist_<id>.csv` y `reports/auditoria_<id>.csv` con los
   candidatos que quedan en los puestos.

Formato esperado en el correo (cuerpo o adjunto):

```json
{
  "id": "V004",
  "titulo": "Desarrollador React",
  "descripcion": "Texto libre del puesto",
  "skills_obligatorios": ["React", "JavaScript"],
  "skills_deseables": ["TypeScript"],
  "experience_required": 2,
  "english_required": "B1",
  "availability_required": "2026-11-01",
  "modality": "remoto"
}
```

En CSV las skills se separan con `;`. Si un correo no trae la vacante, se
informa el motivo y la vigilancia continúa sin detenerse.

## Correos en texto libre

No hace falta JSON. `src/grafo_correo.py` (LangGraph) lee el texto y decide
**por el contexto general**, no por palabras sueltas:

- **Perfil**: el mensaje habla en primera persona, con datos propios
  ("me llamo…", "tengo N años", "mi experiencia", "utilizo…").
- **Puesto**: la organización declara una necesidad de contratación
  ("se busca…", "necesitamos…", "se requiere…") y describe el cargo.
- **Gestión / desconocido**: habla del proyecto, saluda o pide información.
  Mencionar "vacantes" o "requisitos" **no** basta para tomarlo como oferta.

Cada correo queda en `data/correos_recibidos.csv` con el texto original, el
tipo detectado, las señales de contexto y la acción tomada. Para comprobar si
un correo real se clasificó bien, sin guardar nada:

```powershell
python -m src.verificar_correos
```

La verificación se marca en el propio CSV: al reprocesar un correo se actualiza
su fila (`tipo_verificado`, `coincide`).

| Tipo | Qué hace |
|---|---|
| vacante | Guarda en `data/vacantes.json` y corre el matching (`reports/shortlist_<id>.csv`) |
| candidato | Agrega una fila a `data/candidatos.csv` |
| desconocido | Se descarta y se registra el motivo |

Los datos que no vienen en el correo **no se inventan**: se guardan vacíos y
`python -m src.validar_dataset` los reporta.

### Archivos que genera

Solo hay un catálogo y un registro; **no se crea un archivo por correo**:

| Archivo | Contenido |
|---|---|
| `data/candidatos.csv` | Todos los perfiles |
| `data/vacantes.json` | Todas las vacantes |
| `data/correos_recibidos.csv` | Un registro por correo: texto, tipo, señales y acción |
