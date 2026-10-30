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
python -m src.ejecutar_matching V003 --salida reports/salida_V003.json
```

Cada corrida deja:

| Archivo | Contenido |
|---|---|
| `reports/shortlist_<id>.csv` | Los perfiles que ocupan puesto, con puntaje y justificación |
| `reports/auditoria_<id>.csv` | Log de auditoría: iteración, nodo, decisión y motivo (RF-10) |
| `reports/salida_<id>.json` | Respuesta del agente: éxito, relajaciones, consultas, límites y explicación del bloqueo (RF-07, RF-17, RNF-04) |

### Reporte por vacante (RF-11)

```powershell
# Corre el matching de la vacante y deja su reporte en reports/
python -m src.reporte_vacante V001
python -m src.reporte_vacante V003
```

| Archivo | Contenido |
|---|---|
| `reports/reporte_<id>.md` | Reporte legible: shortlist, puntaje desglosado, relajaciones, supuestos y notas |
| `reports/reporte_<id>.json` | El mismo reporte en JSON, para procesarlo |
| `reports/puntajes_<id>.csv` | Una fila por candidato y una columna por componente del puntaje |

El reporte se arma solo con el estado final del matching (no vuelve a puntuar
ni consulta al LLM), así que es reproducible (RNF-03). Trae:

- **Shortlist**: quién ocupa puesto, con puntaje y justificación.
- **Puntaje desglosado**: para cada candidato evaluado, cuántos puntos aportó
  skills obligatorios, deseables, experiencia, inglés y disponibilidad, con
  los datos concretos que lo justifican. La suma de los componentes es el
  puntaje total, y hay una tabla de qué componente descontó más puntos.
- **Criterios relajados**: qué se movió, de qué valor a cuál, en qué orden, y
  la comparación original/vigente (los skills obligatorios nunca cambian).
- **Supuestos**: umbral, pesos, skills inviolables, orden de relajación,
  compatibilidad de modalidad, datos que el reclutador no confirmó y el modo
  de ejecución, cada uno con su fuente.
- **Notas de la corrida**: perfiles sin fecha, fecha relajada usada en la
  comparación y duplicados descartados.

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
| `evaluar_resultado` | RF-05 | Éxito si al menos 3 candidatos superan el umbral; además se explica el bloqueo (RF-07) |
| `relajar_criterios` | RF-06 | Mueve la fecha 2 semanas, luego acepta 1 año menos, luego 1 nivel menos de inglés |
| `finalizar` | RF-07 | Si la shortlist quedó incompleta, entrega los perfiles que hay y dice qué requisito lo impide |

### Shortlist parcial (RF-07)

Si después de las 3 relajaciones no hay 3 candidatos, la corrida **no se
queda sin respuesta**: termina con `estado: incompleta`, deja en la shortlist
los perfiles que sí cumplen (aunque sean 0, 1 o 2) y explica el bloqueo en
`analisis_shortlist` de la salida y en el último evento de auditoría:

| Campo de la salida | Contenido |
|---|---|
| `shortlist_parcial` | `true` si quedan puestos sin cubrir |
| `puestos_libres` | Puestos que no se pudieron cubrir |
| `requisito_bloqueante` | `skills_obligatorios`, `experiencia`, `ingles`, `disponibilidad`, `modalidad` o `umbral` |
| `motivo_incompleta` | Explicación en texto del bloqueo |
| `bloqueantes` | Cada requisito con los perfiles concretos que no lo cumplen |
| `perfiles_entregados` | Los perfiles que sí entran, con puesto, puntaje y justificación |

La explicación se arma con los perfiles que están a menos de 10 puntos del
umbral (o, si ninguno se acerca, con los 5 mejores). Los skills obligatorios
nunca se relajan, así que un puesto que exige skills que nadie tiene aparece
como bloqueado por `skills_obligatorios`.

### Límites por corrida (RNF-04)

| Límite | Valor | Dónde se aplica |
|---|---|---|
| Horas simuladas de monitoreo | 24 h (3 h por lectura de la bandeja) | `limits.max_monitoring_hours` |
| Relajaciones | 3 | `relaxation.max_relaxations` |
| Consultas al reclutador | 3 | `recruiter.max_queries` |
| Llamadas al LLM por vacante | 30 | `llm.max_calls_per_job` |
| Pasos del grafo (`recursion_limit`) | 400 | `limits.recursion_limit` |

La corrida imprime los límites y cuántos pasos usó. Ningún límite se pasa:
las relajaciones, consultas y llamadas al LLM se cortan en el valor
configurado, y si el grafo no termina dentro de `recursion_limit` LangGraph
aborta la corrida. `pasos_grafo` se cuenta con un canal sumable del estado,
así que es exacto aunque LangGraph ejecute nodos en paralelo.

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
| `data/vacantes.json` | El catálogo real: solo las 3 vacantes del lote (V001–V003, ver abajo) |
| `data/bandeja.json` | 11 correos simulados en 24 h, con `vacante_estructurada` (sus vacantes B001–B003 viven solo aquí) |
| `data/cola_vacantes.json` | Cola de vacantes clasificadas (RF-16), con sus duplicados y revisiones |
| `data/reclutador.json` | Respuestas del reclutador, incluida una "no se sabe" |
| `data/config.yaml` | Pesos, umbral, orden de relajación, límites (`limits`) y modo |
| `data/salida.json` | Bandeja de salida donde el agente deja la respuesta (RF-17) |

## Catálogo de vacantes: las 3 del lote (V001–V003)

`data/vacantes.json` contiene **solo** estas tres vacantes, numeradas desde
V001. La bandeja simulada conserva las suyas en `data/bandeja.json` con IDs
`B001`–`B003`, que no chocan con el catálogo (hay una prueba que lo verifica).

Las solicitudes que llegan del reclutador se guardan **siempre como vacante
estructurada en `data/vacantes.json`**: el sistema no se conecta a la base de
datos de la empresa ni a su ATS (por seguridad), así que el JSON es el único
contrato de entrada. El correo / mensaje original queda como contexto en
`descripcion` y lo que el esquema no puede expresar (requisito de país,
seniority, cuántas personas se piden) va en campos extra o en `supuestos`:

| Campo | Uso | Ejemplo |
|---|---|---|
| `seniority` | `junior`, `junior_senior`, `mid_senior`, `senior` | el correo de Java pide "JR and Senior" |
| `vacantes_disponibles` | Cuántas personas pide la vacante | 4 a 8 ingenieros RPG |
| `requisitos_pais` | Restricción de país (no se puntúa, se reporta) | "solamente candidatos de Costa Rica", "US-based; Dallas, TX" |
| `supuestos` | Lo que se dedujo y debe confirmar el reclutador | años, fecha de inicio, modalidad |

| ID | Vacante | Obligatorios | Experiencia | Notas |
|---|---|---|---|---|
| V001 | Ingeniero Java Supply Chain (JR y Senior) | Java, Spring Boot, Kafka, REST API, microservicios, GitLab, CI/CD, Terraform, pruebas automatizadas, New Relic, Splunk, AWS, Kubernetes | 7 | Solo Costa Rica; GCP, bases relacionales y Supply Chain como deseables |
| V002 | Pod EMR: ingeniero Mid-Senior con Claude | Next.js, TypeScript, Claude, arquitectura full-stack escalable, agentes de IA | 5 | 4 puestos; se registra 1 por vacante (ver abajo) |
| V003 | Ingeniero iSeries RPG | IBM i (AS/400), RPG III/IV/ILE/Free, CL, SQL, DB2, integración de sistemas | 10 | 4–8 puestos; **US-based, Dallas TX**, con modalidad presencial: el dataset de Costa Rica no puede cubrirlo |

```powershell
python -m src.ejecutar_matching V001 --salida reports/salida_V001.json
python -m src.reporte_vacante V001
```

Resultado con el dataset actual (39 perfiles únicos, todos backend Python,
Java o JavaScript): **las tres quedan `incompleta`** y explican el bloqueo
por `skills_obligatorios` — nadie tiene el stack completo que pide el correo,
y los skills obligatorios no se relajan. Ese es el comportamiento esperado:
el agente entrega la explicación en vez de inventar candidatos.

Dos cosas que el esquema todavía no modela y se manejan a mano:

- **Varios puestos por vacante** (4 ingenieros EMR, 4–8 RPG). El matching
  arma una shortlist de 3 (`agent.shortlist_size`) y se puede correr una vez
  por posición; `vacantes_disponibles` deja constancia del total.
- **Requisito de país**. Se guarda en `requisitos_pais` pero el puntaje no lo
  evalúa: el reporte debe revisarse a mano antes de enviar el perfil (V003
  pide Dallas, TX).

Para que estos correos se puedan clasificar también desde **texto libre**
(sin `vacante_estructurada`), el catálogo de skills de `src/interpretar_texto.py`
reconoce el vocabulario de este lote: Kafka, Terraform, GitLab, Spring Boot,
New Relic, Splunk, Claude, agentes de IA, infraestructura como código, IBM i,
RPG III/IV/ILE/Free, CL, DB2 y COBOL. "RPG ILE" cuenta también como RPG IV.

## Bandeja simulada: un ciclo por hora (RF-15)

```powershell
# Corre la bandeja de 06:00 a 07:00 del día siguiente (24 h simuladas)
python -m src.bandeja_simulada --reiniciar

# Solo las primeras horas, o viéndola avanzar en vivo (no cambia lo procesado)
python -m src.bandeja_simulada --reiniciar --horas 6
python -m src.bandeja_simulada --reiniciar --ritmo-real 1
```

Un ciclo = **1 hora simulada**. En cada ciclo:

1. Se leen de `data/bandeja.json` los correos que llegaron hasta esa hora.
2. Se ignoran los `message_id` ya procesados; se guardan en
   `data/bandeja_procesados.json`, así un correo nunca se procesa dos veces
   (ni entre ciclos ni entre corridas).
3. Cada correo se **clasifica** (RF-16, ver abajo): solo una **vacante nueva**
   entra a la cola y dispara el matching. Un candidato, una consulta, un
   boletín, una vacante duplicada o una que no trae rol y skills obligatorios
   se registran pero no lanzan el proceso.
4. La vacante se procesa en el mismo ciclo y sale de la cola.

### Clasificación de correos y cola de vacantes (RF-16)

`src/clasificar_correos.py` clasifica cada correo en una de tres clases:

| Clase | Qué significa | ¿Entra a la cola? |
|---|---|---|
| `vacante_nueva` | Describe un puesto con **rol** y **skills obligatorios** | Sí, y dispara el matching |
| `duplicado` | Misma vacante ya recibida (mismo ID o misma huella de rol + skills + criterios), incluidos los reenvíos | No |
| `no_relacionado` | Gestión, candidato, boletín, factura o texto sin un puesto concreto | No |
| `revision_humana` | Parece una vacante pero le falta el rol o los skills obligatorios | No: se marca para una persona |

Reglas que se respetan en las dos fases:

- No se inventan criterios: lo que el correo no dice queda vacío y el agente
  lo reporta como faltante.
- Si la vacante estructurada de la bandeja no coincide con lo que pide el
  texto (por ejemplo, skills o fecha distintos), el correo va a revisión: no
  se procesa dos versiones del mismo puesto.
- La cola queda en `data/cola_vacantes.json` con la vacante, el correo de
  origen, la fase que la clasificó y los duplicados que apuntan a ella.

La fase depende de `AGENTE_MODO` (o del argumento `modo`):

| Fase | Modo | Cómo decide |
|---|---|---|
| 1 | `without_llm` | Reglas deterministas sobre el texto (`interpretar_texto`), sin red |
| 2 | `with_llm` | El LLM clasifica y extrae los campos; el rol, los skills obligatorios, la detección de duplicados y la entrada a la cola **siguen en código**. Si el LLM falla o no devuelve JSON válido, se usan las reglas |

La corrida termina cuando **ya no queda ninguna vacante sin leer** en la
bandeja (las 24 h solo se agotan si no llega ninguna), o al llegar a la hora
máxima. Los correos de gestión, candidato o basura que queden se reportan como
"sin leer al cerrar" pero no alargan la corrida: igual que el caso 1, que
despacha todo en las primeras horas. Lo procesado de esta bandeja:

| Hora | Correo | Acción |
|---|---|---|
| 1 | b0 consulta de proceso | no relacionado (gestión), sin matching |
| 3 | b1 vacante V001 | **vacante nueva**, dispara matching (3 en shortlist) |
| 4 | b10 perfil de Carlos | no relacionado (candidato) |
| 5 | b2 vacante V002 | **vacante nueva**, dispara matching (queda incompleta) |

| 8 | b3 vacante V003 | **vacante nueva**, dispara matching (incompleta, RF-07) |
| 8 | b4 reenvío de V001 | **duplicado** de b1, no repite el matching |
| 9–24 | b5 perfil sin skills, b6 y b10 perfiles, b7–b9 boletines y factura | b5 a revisión humana; el resto no relacionado (sin leer al cerrar) |

### Varias vacantes en una corrida (RF-13)

La bandeja trae más de una vacante y la corrida las procesa **todas**, no solo
la primera. El orden es:

1. En cada ciclo se clasifican los correos y las **vacantes nuevas se encolan**.
2. Al cerrar el ciclo se drena la cola: cada vacante corre su matching
   completo, **una por vez** y en el orden en que llegó el correo.
3. Cada vacante sale de la cola con su resultado guardado, listo para su
   reporte.

En esta bandeja el orden real es `V001 → V002 → V003`, el orden de llegada
de los correos. Si una vacante falla (por ejemplo, por
el `recursion_limit`), se registra el error y **la cola sigue con la
siguiente**: una vacante rota no frena a las demás.

```powershell
# Corre la bandeja y deja un reporte por cada vacante + un índice
python -m src.reporte_vacante
```

Eso genera `reports/bandeja/reporte_<id>.md|json` y `puntajes_<id>.csv` para
B001, B002 y B003, más `reports/bandeja/reportes_bandeja.md` con la tabla de
orden, estado y puestos cubiertos de cada una. Van en su propia carpeta para
no pisar los reportes del catálogo real (`reports/reporte_V001.md`, etc.), que
se llaman igual.

Al terminar, la corrida informa `orden_procesamiento` (el orden de la cola),
`vacantes_en_cola` (las que pasaron por ella) y `vacantes_pendientes` (las que
quedaron si se cortó por hora máxima, normalmente ninguna).

La simulación **no toca el dataset real**: sus candidatos y su catálogo de
vacantes viven en memoria durante la corrida, para no contar dos veces al
mismo candidato en el siguiente matching. Hay una prueba que verifica que
`data/vacantes.json` y `data/candidatos.csv` quedan intactos.

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
  "_nota": "Ejemplo de vacante nueva que llegue por correo; se agrega al catálogo con el ID que traiga.",
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
