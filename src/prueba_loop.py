
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END


# 1. Definir el estado
class Estado(TypedDict):
    contador: int


# 2. Crear un nodo que incrementa el contador
def incrementar(estado: Estado):
    nuevo_contador = estado["contador"] + 1
    print(f"Iteración: {nuevo_contador}")

    return {"contador": nuevo_contador}


# 3. Definir la condición del loop
def decidir(estado: Estado):
    if estado["contador"] < 3:
        return "repetir"

    return "terminar"


# 4. Construir el grafo
grafo = StateGraph(Estado)

grafo.add_node("incrementar", incrementar)

grafo.add_edge(START, "incrementar")

grafo.add_conditional_edges(
    "incrementar",
    decidir,
    {
        "repetir": "incrementar",
        "terminar": END,
    },
)

# 5. Compilar y ejecutar
app = grafo.compile()

resultado = app.invoke({"contador": 0})

print("\nResultado final:")
print(resultado)