
# Diseño del estado del agente de matching

## 1. Propósito

El estado del agente almacena la información necesaria para
procesar una vacante, evaluar candidatos, registrar los resultados
y controlar el flujo de ejecución del grafo de LangGraph.

Durante las primeras etapas, el agente funcionará sin un modelo
de lenguaje (LLM). La evaluación se realizará mediante reglas
deterministas definidas en la configuración del proyecto.

## 2. Campos del estado

| Campo | Tipo propuesto | Propósito |
|---|---|---|
| vacante_actual | dict | Contiene los datos de la vacante que se está procesando. |
| candidatos | list[dict] | Contiene los candidatos cargados desde el CSV. |
| candidatos_filtrados | list[dict] | Guarda los candidatos que pasan los filtros iniciales. |
| resultados | list[dict] | Almacena las puntuaciones y los resultados del matching. |
| relajaciones_aplicadas | list[dict] | Registra los ajustes de criterios aplicados durante la búsqueda. |
| consultas_reclutador | list[dict] | Guarda las consultas y las respuestas relacionadas con los candidatos. |
| auditoria | list[dict] | Registra eventos relevantes del proceso para poder revisarlos. |
| errores | list[str] | Almacena los errores detectados durante la ejecución. |

## 3. Funcionamiento esperado

1. El agente recibe la vacante que debe procesar.
2. Consulta el conjunto de candidatos disponible.
3. Aplica los filtros definidos para la vacante.
4. Evalúa a los candidatos mediante reglas deterministas.
5. Guarda las puntuaciones y los resultados.
6. Si corresponde, registra las relajaciones aplicadas.
7. Registra las consultas realizadas al reclutador.
8. Conserva una auditoría del proceso y de los errores detectados.

## 4. Consideraciones de diseño

- El estado se compartirá entre los nodos del grafo.
- Cada nodo actualizará los campos que le correspondan.
- Los datos originales de candidatos y vacantes deberán conservarse.
- Las relajaciones y las consultas deberán quedar registradas.
- Los campos se podrán ajustar conforme se implementen y prueben
  las funcionalidades del agente.
- El diseño inicial no depende de un proveedor de LLM.

## 5. Estado del entregable

Diseño inicial elaborado durante la Semana 1.
Pendiente de revisión y validación durante la implementación.