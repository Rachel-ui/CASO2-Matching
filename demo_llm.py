#!/usr/bin/env python3
"""Demo visual de RF-01/RF-16 (fase 2) con un LLM simulado.

No hace llamadas reales: `DemoLLM` devuelve un JSON fijo. Para ver el LLM
real se usa `demo_langgraph.py` o `src.clasificar_correos` con la clave
en `.env`.
"""

import os
os.environ['AGENTE_MODO'] = 'with_llm'

from src.clasificar_correos import clasificar_con_llm


class DemoLLM:
    """Simula respuesta realista del LLM (sin necesitar API real)."""
    def invoke(self, mensajes):
        import json
        respuesta = {
            "clase": "vacante_nueva",
            "motivo": "El correo solicita un desarrollador backend con stack Python.",
            "tipo_texto": "vacante",
            "vacante": {
                "titulo": "Desarrollador Backend Python",
                "descripcion": "Se busca desarrollador para equipo de plataforma.",
                "skills_obligatorios": ["Python", "SQL", "Git", "REST API"],
                "skills_deseables": ["Docker", "FastAPI", "Django"],
                "experience_required": 3,
                "english_required": "B1",
                "availability_required": "2026-10-25",
                "modality": "remoto"
            }
        }
        class R:
            content = json.dumps(respuesta)
        return R()


def main():
    llm = DemoLLM()

    correo = {
        "message_id": "demo-001",
        "timestamp": "2026-10-20T08:10:00",
        "remitente": "rrhh@empresa.example",
        "asunto": "Solicitud de vacante: Desarrollador Backend Python",
        "cuerpo": """Hola, necesitamos cubrir un puesto de Desarrollador Backend Python 
para el equipo de plataforma. Se requiere Python, SQL, Git y REST API; 
deseables Docker, FastAPI y Django. Experiencia mínima de 3 años, 
inglés B1, modalidad remoto y disponible para iniciar el 25/10/2026."""
    }

    print("=" * 60)
    print("CORREO DE ENTRADA")
    print("=" * 60)
    print(correo["cuerpo"])
    print()

    resultado = clasificar_con_llm(correo, llm, vacantes_recibidas=[])

    print("=" * 60)
    print("RESULTADO CLASIFICACIÓN (RF-16 fase 2)")
    print("=" * 60)
    print(f"Clase: {resultado['clase']}")
    print(f"Fuente: {resultado['fuente']}")
    print(f"Motivo: {resultado['motivo']}")
    print(f"LLM calls: {resultado['llm_calls']}")
    print()

    print("=" * 60)
    print("REQUISITOS EXTRAÍDOS (RF-01) - Formato legible")
    print("=" * 60)
    req = resultado.get("requisitos", {})
    for k, v in req.items():
        print(f"  {k}: {v}")
    print()

    print("=" * 60)
    print("VACANTE INTERNA (para matching)")
    print("=" * 60)
    vac = resultado.get("vacante", {})
    for k, v in vac.items():
        print(f"  {k}: {v}")
    print()

    print("=" * 60)
    print("ADVERTENCIAS (campos que el LLM no pudo devolver bien)")
    print("=" * 60)
    for a in resultado.get("advertencias", []):
        print(f"  - {a}")
    if not resultado.get("advertencias"):
        print("  (ninguna)")


if __name__ == "__main__":
    main()