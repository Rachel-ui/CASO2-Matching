
# Diseño del estado del agente de matching

## 1. Propósito

El estado del agente almacena la información compartida entre los nodos del grafo de LangGraph durante el proceso de selección de candidatos para una vacante.

En la primera etapa, el agente funcionará sin un modelo de lenguaje (LLM). El filtrado y la evaluación inicial se realizarán mediante reglas deterministas definidas en la configuración del proyecto.

El diseño contempla futuras etapas de integración con un LLM, consultas al reclutador, relajación controlada de criterios y revisión humana.

## 2. Campos del estado

| Campo | Tipo propuesto | Propósito |
|---|---|---|
| vacante_actual | dict | Contiene la vacante que se está procesando. |
| candidatos | list[dict] | Contiene los perfiles cargados desde el archivo CSV. |
| candidatos_filtrados | list[dict] | Almacena los candidatos que superan los filtros iniciales. |
| resultados | list[dict] | Guarda las puntuaciones, los motivos de evaluación y los resultados del matching. |
| relajaciones_aplicadas | list[dict] | Registra los criterios relajados y las razones para aplicarlos. |
| consultas_reclutador | list[dict] | Registra las consultas realizadas al reclutador y sus respuestas. |
| auditoria | list[dict] | Conserva eventos relevantes para rastrear las decisiones del agente. |
| errores | list[str] | Almacena los errores detectados durante la ejecución. |
| llm_calls | int | Contabiliza las llamadas al modelo de lenguaje cuando se integre. |
| requiere_revision_humana | bool | Indica si el resultado debe pasar por una revisión humana. |
| estado | str | Identifica la etapa actual del procesamiento. |

## 3. Flujo de funcionamiento esperado

1. Inicializar el estado con la vacante y los candidatos.
2. Validar los datos necesarios para procesar la vacante.
3. Filtrar los candidatos según los criterios aplicables.
4. Evaluar la compatibilidad de los candidatos que continúen en el proceso.
5. Registrar las puntuaciones y los motivos de cada resultado.
6. Determinar si se requiere una relajación de criterios.
7. Registrar las consultas al reclutador cuando sean necesarias.
8. Preparar los resultados para su revisión.
9. Registrar los eventos y errores relevantes durante el proceso.

Las relajaciones, las consultas al reclutador, el uso del LLM y la aprobación humana se incorporarán progresivamente, de acuerdo con las etapas del proyecto.

## 4. Reglas de diseño

- El estado será compartido entre los nodos del grafo.
- Cada nodo actualizará únicamente los campos que le correspondan.
- Los datos originales de candidatos y vacantes se conservarán.
- Las puntuaciones y decisiones deberán poder justificarse mediante registros.
- Los errores y las operaciones relevantes deberán quedar documentados.
- Las llamadas al LLM, cuando se incorporen, deberán respetar los límites definidos en la configuración.
- Los campos y las transiciones se validarán durante la implementación y las pruebas.

## 5. Alcance de la primera implementación

La primera implementación se centrará en inicializar el estado, validar los datos, filtrar candidatos y preparar la estructura de resultados mediante reglas deterministas.

La integración con el LLM, las relajaciones, las consultas al reclutador y la revisión humana se implementarán en las etapas posteriores correspondientes.

## 6. Estado del entregable

Documento de diseño inicial correspondiente a la Semana 1.

Pendiente de implementar el estado en Python, conectarlo con el grafo de LangGraph y verificar su funcionamiento mediante pruebas.