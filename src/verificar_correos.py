
"""Verifica a mano la clasificación de los correos reales de la bandeja.

Solo lee: no guarda vacantes, candidatos ni registros. Sirve para revisar si
el contexto se interpretó bien antes de dejar que el correo se procese.
"""

import sys

from dotenv import load_dotenv

from src.agentmail_cliente import AgentMailCliente
from src.interpretar_texto import interpretar


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv()

    with AgentMailCliente() as cliente:
        for mensaje in cliente.listar_mensajes(limite=10):
            detalle = cliente.obtener_mensaje(mensaje.message_id)
            resultado = interpretar(detalle.cuerpo)
            print(f"\nAsunto: {detalle.asunto}")
            print(f"Tipo detectado: {resultado.tipo}")
            for grupo, oraciones in resultado.evidencia.items():
                if oraciones:
                    print(f"  {grupo}: {oraciones[0][:90]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
