
"""Lee los correos de la bandeja de AgentMail y muestra las solicitudes de vacante.

Uso:
    python -m src.leer_correos                 # últimos 10 correos
    python -m src.leer_correos --limite 5      # últimos 5
    python -m src.leer_correos --ver <message_id>   # cuerpo completo de uno
    python -m src.leer_correos --esperar           # vigila hasta que llegue uno nuevo
    python -m src.leer_correos --vigilar           # continuo: guarda la vacante y hace el matching

Requiere AGENTMAIL_API_KEY y AGENTMAIL_INBOX_ID en el archivo .env (RNF-09).
"""

import argparse
import sys
from datetime import datetime

from dotenv import load_dotenv

from src.agentmail_cliente import MIN_INTERVALO, AgentMailCliente, Correo, ErrorAgentMail


def _configurar_salida() -> None:
    """La consola de Windows usa cp1252 y falla con caracteres no latinos."""

    for flujo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(flujo, "reconfigure", None)
        if reconfigurar is not None:
            try:
                reconfigurar(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _hora() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _vigilar_en_continuo(cliente: AgentMailCliente, argumentos) -> None:
    """Procesa cada correo nuevo y vuelve a esperar; solo lo reporta si falla."""

    from src.procesar_correo import procesar_correo_nuevo

    while True:
        correos = cliente.esperar_mensaje_nuevo(
            intervalo=argumentos.intervalo,
            tiempo_maximo=argumentos.tiempo_maximo,
            aviso=lambda mensaje: print(f"[{_hora()}] {mensaje}", flush=True),
        )
        for correo in correos:
            print(f"\n[{_hora()}]Procesando '{correo.asunto}' de {correo.remitente}")
            procesar_correo_nuevo(correo, cliente)


def _mostrar(correo: Correo) -> None:
    print(f"\nAsunto: {correo.asunto}")
    print(f"De: {correo.remitente}")
    print(f"Fecha: {correo.fecha}")
    print(f"ID: {correo.message_id}")
    print(
        "Adjuntos: "
        + (", ".join(a.filename or a.attachment_id for a in correo.adjuntos) or "ninguno")
    )
    print("\nCuerpo:\n" + (correo.cuerpo or "(sin texto)"))


def main() -> int:
    _configurar_salida()
    load_dotenv()

    parser = argparse.ArgumentParser(description="Consultar la bandeja de AgentMail.")
    parser.add_argument("--limite", type=int, default=10, help="Cantidad de correos a revisar.")
    parser.add_argument("--ver", help="ID del mensaje cuyo cuerpo completo se quiere ver.")
    parser.add_argument(
        "--todas",
        action="store_true",
        help="Muestra también los correos que no parecen solicitudes de vacante.",
    )
    parser.add_argument(
        "--vigilar",
        action="store_true",
        help=(
            "Vigilancia continua: cada correo nuevo se guarda en data/vacantes.json "
            "y se ejecuta el matching."
        ),
    )
    parser.add_argument(
        "--esperar",
        action="store_true",
        help="Vigila la bandeja hasta que llegue un correo nuevo y lo muestra.",
    )
    parser.add_argument(
        "--intervalo",
        type=float,
        default=MIN_INTERVALO,
        help=f"Segundos entre consultas (mínimo {MIN_INTERVALO:g}).",
    )
    parser.add_argument(
        "--tiempo-maximo",
        type=float,
        default=None,
        help="Segundos máximos de vigilancia (por defecto, sin límite).",
    )
    argumentos = parser.parse_args()

    try:
        with AgentMailCliente() as cliente:
            if argumentos.vigilar or argumentos.esperar:
                print(
                    f"Esperando correo nuevo en {cliente.inbox_id}. "
                    "Ctrl+C para salir.",
                    flush=True,
                )
                if argumentos.vigilar:
                    _vigilar_en_continuo(cliente, argumentos)
                    return 0

                adultos = cliente.esperar_mensaje_nuevo(
                    intervalo=argumentos.intervalo,
                    tiempo_maximo=argumentos.tiempo_maximo,
                    aviso=lambda mensaje: print(f"[{_hora()}] {mensaje}", flush=True),
                )
                for correo in adultos:
                    _mostrar(correo)
                return 0

            if argumentos.ver:
                correo = cliente.obtener_mensaje(argumentos.ver)
                _mostrar(correo)
                return 0

            if argumentos.todas:
                correos = cliente.listar_mensajes(limite=argumentos.limite)
                titulo = "Correos de la bandeja"
            else:
                correos = cliente.buscar_solicitudes_vacante(limite=argumentos.limite)
                titulo = "Solicitudes de vacante detectadas"

            print(f"{titulo} ({len(correos)}):\n")
            for correo in correos:
                adjuntos = ", ".join(a.filename or a.attachment_id for a in correo.adjuntos)
                print(f"- {correo.message_id}")
                print(f"  {correo.fecha} | {correo.direccion_remitente} | {correo.asunto}")
                if adjuntos:
                    print(f"  Adjuntos: {adjuntos}")

    except ErrorAgentMail as error:
        print(f"Error: {error}")
        return 1
    except TimeoutError as error:
        print(f"Sin novedades: {error}")
        return 2
    except KeyboardInterrupt:
        print("\nVigilancia detenida por el usuario.")
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
