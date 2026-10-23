"""Configuración común de las pruebas.

Las pruebas nunca deben tomar el modo del `.env` local: si allí está
`with_llm`, el grafo intentaría llamar a OpenRouter en cada corrida. Por eso
el modo por defecto de las pruebas es `without_llm`; la prueba que necesita
el modo con LLM lo activa con `monkeypatch.setenv`.
"""

import os

from src.configuracion import MODO_SIN_LLM


os.environ["AGENTE_MODO"] = MODO_SIN_LLM
